#!/usr/bin/env python3
"""Render the current vertical SDR mixed edit locally; never overwrite media.

Stills must already be orientation-correct full-resolution sRGB JPEGs. Live Photo
pairing and anchor provenance are editorial inputs, not inferred by this tool.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

import montage as m

Error = m.Error
TAGS = ['-color_primaries', 'bt709', '-color_trc', 'bt709',
        '-colorspace', 'bt709', '-color_range', 'tv']
# JPEG is full-range YCbCr (601 coefficients), with an sRGB transfer curve.
# Explicitly linearize sRGB before applying BT.709's transfer and matrix.
STILL_COLOR = ('zscale=pin=bt709:tin=iec61966-2-1:min=170m:rin=full:p=bt709:t=linear:m=gbr:r=full,'
               'format=gbrpf32le,zscale=p=bt709:t=bt709:m=bt709:r=limited,'
               'format=yuv420p,')


def live_color_filter(metadata, source):
    """Keep the tested HLG path; transform tagged SDR gamut/matrix/range."""
    hdr = m.color_filter(metadata, source)
    if hdr:
        return hdr
    v = stream(metadata, 'video')
    fields = ('color_primaries', 'color_transfer', 'color_space', 'color_range')
    values = [v.get(k, 'unknown') for k in fields]
    unknown = {'unknown', 'unspecified'}
    conventional = ({'bt709'}, {'bt709'}, {'bt709'}, {'tv'})
    # Preserve the existing helper's assumption for unspecified ordinary SDR.
    # A tagged wider gamut needs complete interpretation; never guess its matrix.
    if all(value in allowed or value in unknown for value, allowed in zip(values, conventional)):
        return ''
    if any(value in unknown for value in values):
        raise Error(f'Incomplete tagged SDR color metadata: {source}: {values}')
    p, t, matrix, rng = values
    supported_p = {'bt709', 'bt470m', 'bt470bg', 'smpte170m', 'smpte240m',
                   'bt2020', 'smpte431', 'smpte432', 'film', 'ebu3213', 'jedec-p22'}
    supported_t = {'bt709', 'smpte170m', 'smpte240m', 'iec61966-2-1',
                   'bt2020-10', 'bt2020-12', 'gamma22', 'gamma28'}
    supported_m = {'bt709', 'smpte170m', 'smpte240m', 'bt470bg', 'fcc', 'bt2020nc', 'bt2020c', 'gbr'}
    if p not in supported_p or t not in supported_t or matrix not in supported_m or rng not in {'pc', 'tv'}:
        raise Error(f'Unsupported tagged SDR color metadata: {source}: {values}')
    t = {'gamma22': 'bt470m', 'gamma28': 'bt470bg'}.get(t, t)
    return (f'zscale=pin={p}:tin={t}:min={matrix}:rin={rng}:p={p}:t=linear:m=gbr:r=full,'
            'format=gbrpf32le,zscale=p=bt709:t=bt709:m=bt709:r=limited,'
            'format=yuv420p,')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def probe(path, count=False):
    args = [m.FFPROBE, '-v', 'error']
    if count:
        args += ['-count_frames']
    return json.loads(m.run(args + ['-show_streams', '-show_format', '-of', 'json', path]))


def stream(info, kind):
    return next((s for s in info['streams'] if s['codec_type'] == kind), {})


def packets(path):
    return [p['data_hash'] for p in json.loads(m.run([
        m.FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_packets',
        '-show_data_hash', 'sha256', '-show_entries', 'packet=data_hash',
        '-of', 'json', path]))['packets']]


def audio_bytes(path):
    return m.run([m.FFMPEG, '-v', 'error', '-nostdin', '-i', path,
                  '-map', '0:a:0', '-f', 's16le', '-acodec', 'pcm_s16le', '-'], binary=True)


def verify(path, frames, pcm=True):
    info = probe(path, True)
    v, a = stream(info, 'video'), stream(info, 'audio')
    expected = {'codec_name': 'h264', 'width': 1080, 'height': 1920,
                'pix_fmt': 'yuv420p', 'sample_aspect_ratio': '1:1',
                'profile': 'High', 'level': 40,
                'color_primaries': 'bt709', 'color_transfer': 'bt709',
                'color_space': 'bt709', 'color_range': 'tv', 'has_b_frames': 0}
    if any(v.get(k) != value for k, value in expected.items()):
        raise Error(f'Incompatible video parameters: {path}: ' + str({k: v.get(k) for k, value in expected.items() if v.get(k) != value}))
    if int(v.get('nb_read_frames', -1)) != frames or v.get('side_data_list') or v.get('tags', {}).get('rotate'):
        raise Error(f'Frame count or inherited side data mismatch: {path}')
    if a.get('sample_rate') != '48000' or a.get('channels') != 2:
        raise Error(f'Incompatible audio: {path}')
    if pcm and (a.get('codec_name') != 'pcm_s16le' or len(audio_bytes(path)) != frames * 1600 * 4):
        raise Error(f'PCM sample count mismatch: {path}')
    m.run([m.FFMPEG, '-v', 'error', '-nostdin', '-i', path,
           '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
    return info


def live_window_filter(selection):
    """Keep the declared time origin; only pass frames inside this window."""
    start = selection['start']
    end = start + selection['frames'] / 30
    return (f'trim=start={start:.12f}:end={end:.12f},'
            f'setpts=PTS-{start:.12f}/TB,'
            'fps=30:start_time=0:round=near:eof_action=pass,')


def live_resampling_plan(selection, source, info=None):
    # Measure the same bounded temporal filter before any destination is made.
    # Native-size frame hashes avoid a second color conversion/vertical encode.
    text = m.run([m.FFMPEG, '-v', 'error', '-nostdin', '-i', source,
                  '-map', '0:v:0', '-an', '-vf', live_window_filter(selection) +
                  f"trim=end_frame={selection['frames']}", '-f', 'framehash', '-'])
    hashes = [line.rsplit(',', 1)[-1].strip() for line in text.splitlines()
              if line and not line.startswith('#')]
    missing = selection['frames'] - len(hashes)
    if not hashes or missing not in {0, 1}:
        raise Error(f'Live window needs more than one edge-padding frame: {source}: {missing}')
    v = stream(info or probe(source), 'video')
    numerator, denominator = map(int, v['time_base'].split('/'))
    decoded = json.loads(m.run([m.FFPROBE, '-v', 'error', '-select_streams', 'v:0',
                               '-show_frames', '-show_entries', 'frame=best_effort_timestamp',
                               '-of', 'json', source]))['frames']
    timestamps = [f['best_effort_timestamp'] * numerator / denominator for f in decoded
                  if 'best_effort_timestamp' in f]
    start = selection['start']
    end = start + selection['frames'] / 30
    inside = [t for t in timestamps if start - 1e-9 <= t < end - 1e-9]
    if not inside:
        raise Error(f'No decoded frame within Live Photo window: {source}')
    return {'method': 'explicit_source_window_preserved_time_origin_fps_start_zero',
            'selected_source_frames': len(inside),
            'first_selected_source_frame_seconds': inside[0],
            'last_selected_source_frame_seconds': inside[-1],
            'leading_hold_seconds': max(0, inside[0] - start),
            'source_window_start_seconds': selection['start'],
            'source_window_end_seconds': selection['start'] + selection['frames'] / 30,
            'anchor_output_seconds': selection['anchor_seconds'] - selection['start'],
            'anchor_nearest_output_frame': round((selection['anchor_seconds'] - selection['start']) * 30),
            'resampled_frames_before_edge_padding': len(hashes),
            'trailing_clone_padding_frames': missing,
            'identical_consecutive_resampled_frame_hashes': sum(a == b for a, b in zip(hashes, hashes[1:])),
            'note': 'CFR resampling may repeat selected source frames; any extra trailing clone is bounded to one frame. No source frame outside the chosen window is used.'}


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise Error(f'{label} must be finite numeric')
    return value


def validate(edit, work, output):
    work, output = Path(work).absolute(), Path(output).absolute()
    if work.exists() or output.exists() or work.is_symlink() or output.is_symlink():
        raise Error('Work directory and output must be new paths')
    for destination in (work.resolve(), output.resolve()):
        if any((parent / '.git').exists() for parent in (destination, *destination.parents)):
            raise Error('Media work/output must stay outside Git repositories')
    if output.suffix.lower() != '.mp4':
        raise Error('Output must be an MP4')
    if any(edit.get(k) != val for k, val in {'version': 2, 'fps': 30, 'width': 1080, 'height': 1920}.items()):
        raise Error('Expected version 2, 1080x1920, 30fps edit')
    min_frames = edit.get('min_frames', 24)
    if type(min_frames) is not int or min_frames not in {9, 15, 24}:
        raise Error('min_frames must be explicitly 9/15 or the default 24')
    still_min_frames = edit.get('still_min_frames', min_frames)
    if type(still_min_frames) is not int or still_min_frames not in {9, 12, 15, 18, 24}:
        raise Error('still_min_frames must be explicitly 9/12/15/18 or the default minimum')
    selections = edit.get('selections')
    if not isinstance(selections, list) or not selections:
        raise Error('Selections must be a nonempty list')
    seen, checked = set(), []
    for s in selections:
        if not isinstance(s, dict) or s.get('type') not in {'still', 'live_photo', 'video_segment'}:
            raise Error('Unknown selection type')
        asset = s.get('asset_id')
        if not isinstance(asset, str) or not asset.strip() or asset in seen:
            raise Error('Asset IDs must be nonempty and unique')
        seen.add(asset)
        n = s.get('frames')
        floor = still_min_frames if s['type'] == 'still' else min_frames
        if type(n) is not int or not floor <= n <= 60 or (n > 30 and s.get('extended') is not True):
            raise Error(f'Require {floor}..60 frames for {s["type"]}; cuts over 30 need extended=true')
        if not isinstance(s.get('reason'), str) or not s['reason'].strip():
            raise Error('Each cut needs a reason')
        p = Path(s.get('path', ''))
        if not p.is_absolute() or not p.is_file():
            raise Error('Each source must be an absolute existing file')
        p = p.resolve()
        if work.resolve() == p or work.resolve() in p.parents or output.resolve() == p:
            raise Error('Work/output must not overwrite or contain a source')
        digest = s.get('source_sha256', '')
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest) or sha256(p) != digest:
            raise Error(f'Source SHA-256 mismatch: {asset}')
        gain = finite(s.get('audio_gain_db', 0), 'audio_gain_db')
        info = probe(p)
        v = stream(info, 'video')
        color = ''
        resampling = None
        if s['type'] == 'video_segment':
            verify(p, n)
        elif s['type'] == 'still':
            if p.suffix.lower() not in {'.jpg', '.jpeg'} or v.get('codec_name') != 'mjpeg':
                raise Error('Still input must be a prepared sRGB JPEG')
            if v.get('side_data_list') or v.get('tags', {}).get('rotate'):
                raise Error('Still must already be orientation-correct')
            color = STILL_COLOR
        else:
            start = finite(s.get('start'), 'start')
            anchor = finite(s.get('anchor_seconds'), 'anchor_seconds')
            if not isinstance(s.get('anchor_method'), str) or not s['anchor_method'].strip():
                raise Error('Live Photo requires recorded anchor_method')
            metadata = m.probe(p)
            if start < 0 or start + n / 30 > metadata['duration'] + 1e-6 or not start <= anchor < start + n / 30:
                raise Error('Live Photo cut must include anchor and fit available motion')
            color = live_color_filter(metadata, p)
            resampling = live_resampling_plan(s, p, info)
        checked.append((s, p, color, info, gain, resampling))
    m.check_filters([row[2] for row in checked])
    return checked


def render(edit, work, output):
    work, output = Path(work).absolute(), Path(output).absolute()
    checked = validate(edit, work, output)  # Complete validation before creating anything.
    work.mkdir(parents=True, exist_ok=False)
    paths, hashes, timeline, cursor = [], [], [], 0
    for i, (s, p, color, info, gain, resampling) in enumerate(checked, 1):
        n = s['frames']
        out = work / f'{i:03}.mkv'
        if s['type'] == 'video_segment' and gain == 0:
            # Preserve both video packets and the already finished PCM audio exactly.
            shutil.copyfile(p, out)
        else:
            cmd = [m.FFMPEG, '-v', 'error', '-nostdin']
            if s['type'] == 'still':
                cmd += ['-loop', '1', '-framerate', '30']
            cmd += ['-i', p]
            audible = s['type'] != 'still' and bool(stream(info, 'audio'))
            if not audible:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            cmd += ['-map', '0:v:0', '-map', '0:a:0' if audible else '1:a:0']
            if s['type'] != 'live_photo':
                cmd += ['-t', str(n / 30)]
            if s['type'] == 'video_segment':
                cmd += ['-c:v', 'copy']
            else:
                temporal = ''
                if s['type'] == 'live_photo':
                    temporal = live_window_filter(s)
                    if resampling['trailing_clone_padding_frames']:
                        temporal += 'tpad=stop_mode=clone:stop=1,'
                vf = temporal + color + m.fit_filter(1080, 1920) + (',' if temporal else ',fps=30,') + f'trim=end_frame={n},settb=1/30,setpts=N,format=yuv420p,sidedata=mode=delete'
                cmd += ['-vf', vf, '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                        '-bf', '0', '-threads', '2', '-pix_fmt', 'yuv420p'] + TAGS
            audio_window = ''
            if s['type'] == 'live_photo' and audible:
                audio_window = f"atrim=start={s['start']:.12f}:end={s['start'] + n / 30:.12f},asetpts=PTS-STARTPTS,"
            af = audio_window + f'aresample=48000,volume={gain}dB,apad,atrim=end_sample={n * 1600},asetpts=N/SR/TB'
            if s['type'] == 'live_photo':
                af += f',afade=t=in:d=0.01,afade=t=out:st={n / 30 - 0.01:.9f}:d=0.01'
            cmd += ['-af', af, '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2',
                    '-map_metadata', '-1', '-n', out]
            m.run(cmd)
        verify(out, n)
        current = packets(out)
        if s['type'] == 'video_segment' and current != packets(p):
            raise Error('Copied segment video packets changed')
        hashes.extend(current)
        paths.append(out)
        timeline.append({**s, **({'video_resampling': resampling} if resampling else {}), 'segment': str(out), 'timeline_start_frame': cursor, 'timeline_end_frame': cursor + n})
        cursor += n
        print(f'Verified cut {i}: {s["type"]}, {n} frames', flush=True)
    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{p.name}'\n" for p in paths))
    output.parent.mkdir(parents=True, exist_ok=True)
    m.run([m.FFMPEG, '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-auto_convert', '0',
           '-i', concat, '-map', '0:v:0', '-map', '0:a:0', '-t', str(cursor / 30), '-c:v', 'copy',
           '-bsf:v', 'setts=time_base=1/90000:pts=N*3000:dts=N*3000:duration=3000',
           '-video_track_timescale', '90000', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
           *TAGS, '-map_metadata', '-1', '-movflags', '+faststart', '-n', output])
    final = verify(output, cursor, pcm=False)
    v = stream(final, 'video')
    if v['avg_frame_rate'] != '30/1' or abs(float(v['duration']) - cursor / 30) > 1e-7 or packets(output) != hashes:
        raise Error('Concat timing or packet preservation failed')
    # Recheck source identities after rendering as well.
    if any(sha256(p) != s['source_sha256'] for s, p, *_ in checked):
        raise Error('Source changed during render')
    report = {'output': str(output), 'fps': 30, 'frames': cursor, 'duration_seconds': cursor / 30,
              'video_packets_preserved': True, 'min_frames': edit.get('min_frames', 24),
              'timing_override_declared': 'min_frames' in edit,
              'still_min_frames': edit.get('still_min_frames', edit.get('min_frames', 24)),
              'still_timing_override_declared': 'still_min_frames' in edit, 'cuts': timeline, 'probe': final}
    (work / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edit', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffmpeg', default=m.FFMPEG)
    args = parser.parse_args()
    m.FFMPEG = shutil.which(args.ffmpeg or '')
    if not m.FFMPEG or not m.FFPROBE:
        parser.error('ffmpeg and ffprobe are required')
    try:
        report = render(json.loads(args.edit.read_text()), args.work_dir, args.output)
    except (Error, ValueError, OSError, KeyError, TypeError) as e:
        parser.exit(1, f'{e}\n')
    print(json.dumps({k: report[k] for k in ('output', 'frames', 'duration_seconds', 'video_packets_preserved')}))


if __name__ == '__main__':
    main()
