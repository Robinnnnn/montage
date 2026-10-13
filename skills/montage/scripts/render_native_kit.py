#!/usr/bin/env python3
"""Build a one-picture-encode 3:4 kit from pinned, reviewed native windows.

Dry run performs every identity/color/bounded temporal check without writing.
Execute creates separate fresh work and kit directories outside Git. The kit's
relative timeline is portable; native editor construction remains a separate step.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import shutil
import sys

import render_mixed as mixed
import reframe_mixed as verify
import montage as m

Error = verify.Error
# Bound reused native temporal preflight: FFmpeg two threads, ffprobe one.
_base_run = m.run

def bounded_run(argv, binary=False):
    if str(argv[0]) == str(m.FFMPEG):
        argv = [argv[0], '-threads', '2', '-filter_threads', '2', *argv[1:]]
        if '-i' in argv:
            argv = [*argv[:-1], '-threads', '2', argv[-1]]
    elif str(argv[0]) == str(m.FFPROBE):
        argv = [argv[0], '-threads', '1', *argv[1:]]
    return _base_run(argv, binary=binary)
m.run = bounded_run


def require(condition, message):
    if not condition:
        raise Error(message)


def fitted_rect(info):
    v = mixed.stream(info, 'video')
    w, h = v['width'], v['height']
    sar = v.get('sample_aspect_ratio', '1:1')
    a, b = map(int, sar.split(':')) if ':' in sar else (1, 1)
    dar = w * (a / b if a and b else 1) / h
    rotation = float(v.get('tags', {}).get('rotate', 0))
    for side in v.get('side_data_list', []):
        rotation = float(side.get('rotation', rotation))
    if abs(rotation) % 180 == 90:
        dar = 1 / dar
    width = max(2, math.floor(min(1080, 1920 * dar) / 2) * 2)
    height = max(2, math.floor(min(1920, 1080 / dar) / 2) * 2)
    return dict(x=((1080 - width) // 2) // 2 * 2,
                y=((1920 - height) // 2) // 2 * 2, width=width, height=height)


def validate(plan, work, kit, workers=2):
    require(all(plan.get(k) == v for k, v in dict(version=1, fps=30, width=1080, height=1440).items()),
            'Expected version1, fps30, 1080x1440 plan')
    require(type(workers) is int and 1 <= workers <= 2, 'workers must be1 or2')
    baseline_path = verify.absolute_file(plan.get('baseline_verification'), 'baseline_verification')
    exclusion_path = verify.absolute_file(plan.get('excluded_ids'), 'excluded_ids')
    verify.check_hash(baseline_path, plan.get('baseline_verification_sha256'), 'Baseline')
    verify.check_hash(exclusion_path, plan.get('excluded_ids_sha256'), 'Exclusions')
    baseline = json.loads(baseline_path.read_text())
    exclusions = json.loads(exclusion_path.read_text())
    if isinstance(exclusions, dict):
        exclusions = exclusions.get('excluded_ids')
    require(isinstance(exclusions, list) and all(isinstance(x, str) for x in exclusions), 'Invalid holdlist')
    cuts = plan.get('cuts')
    require(isinstance(cuts, list) and bool(cuts), 'cuts must be nonempty')
    old = baseline['cuts']
    ids = [c['asset_id'] for c in cuts]
    require(len(set(ids)) == len(ids) and ids == [c['asset_id'] for c in old],
            'Selections and order must exactly match baseline')
    require(not set(ids).intersection(exclusions), 'Selected asset is on exclusion holdlist')
    total = sum(c['frames'] for c in cuts)
    require(plan.get('expected_cuts') == len(cuts) and plan.get('expected_frames') == total, 'Expected totals mismatch')
    if 'expected_counts' in plan:
        require(plan['expected_counts'] == dict(Counter(c['type'] for c in cuts)), 'Expected type counts mismatch')
    protected = [baseline_path, exclusion_path]
    preliminary = []
    for cut, original in zip(cuts, old):
        for key in ('original_source_identity', 'chronology', 'capture_datetime', 'anchor_method', 'pairing'):
            if key in cut:
                require(cut[key] == original.get(key), f'Baseline provenance mismatch: {key}')
        expected_type = 'native_video' if original['type'] == 'video_segment' else original['type']
        require(cut.get('type') == expected_type, 'Baseline type mismatch')
        require(type(cut['frames']) is int and 1 <= cut['frames'] <= 45, 'frames must be1..45')
        for key in ('reason', 'framing_reason'):
            require(isinstance(cut.get(key), str) and bool(cut[key].strip()), f'Every cut needs {key}')
        source = verify.absolute_file(cut.get('path'), 'path')
        identity = original['original_source_identity'] if expected_type == 'native_video' else dict(path=original['path'], sha256=original['source_sha256'])
        require(source == Path(identity['path']).resolve() and cut['source_sha256'] == identity['sha256'], 'Baseline native source identity mismatch')
        active = verify.rect(cut.get('active_rect'), 'active_rect')
        crop = verify.rect(cut.get('crop_rect'), 'crop_rect')
        require(active == original['active_rect'] and crop == original['crop_rect'], 'Baseline geometry mismatch')
        require(verify.contained(crop, active) and crop['width'] * 4 == crop['height'] * 3, 'Crop outside active content or not3:4')
        gain = mixed.finite(cut.get('audio_gain_db', 0), 'audio_gain_db')
        for path_key, hash_key in [('original_still_path', 'original_still_sha256')]:
            if path_key in original:
                require(cut.get(path_key, original[path_key]) == original[path_key] and cut.get(hash_key, original[hash_key]) == original[hash_key], 'Original still provenance mismatch')
                p = verify.absolute_file(original[path_key], path_key)
                verify.check_hash(p, original[hash_key], 'Original still')
                protected.append(p)
        protected.append(source)
        preliminary.append(dict(cut=cut, original=original, path=source, gain=gain))
    require(work != kit and work not in kit.parents and kit not in work.parents, 'Work and kit must be separate fresh paths')
    for dest in (work, kit):
        require(not dest.exists() and not dest.is_symlink(), 'Work and kit must be fresh paths')
        require(not any((p / '.git').exists() for p in (dest, *dest.parents)), 'Keep media outside Git')
        require(not any(dest == p or dest in p.parents for p in protected), 'Destination contains protected input')

    def inspect(row):
        c, p = row['cut'], row['path']
        verify.check_hash(p, c['source_sha256'], 'Source')
        info = mixed.probe(p)
        require(fitted_rect(info) == c['active_rect'], f'Native fitting geometry mismatch: {c["asset_id"]}: {fitted_rect(info)}')
        temporal = None
        if c['type'] == 'still':
            v = mixed.stream(info, 'video')
            require(p.suffix.lower() in {'.jpg', '.jpeg'} and v.get('codec_name') == 'mjpeg' and not v.get('side_data_list') and not v.get('tags', {}).get('rotate'), 'Still must be prepared orientation-correct sRGB JPEG')
            color = mixed.STILL_COLOR
        else:
            start = mixed.finite(c.get('start'), 'start')
            metadata = m.probe(p)
            end = start + c['frames'] / 30
            require(start >= 0 and end <= metadata['duration'] + 1e-6, 'Source window exceeds primary video bounds')
            anchor = c.get('anchor_seconds', start)
            if c['type'] == 'live_photo':
                require(anchor == row['original']['anchor_seconds'] and start <= anchor < end, 'Live Photo window must contain pinned anchor')
                require(bool(row['original'].get('anchor_method')), 'Missing verified anchor provenance')
            color = mixed.live_color_filter(metadata, p)
            temporal = mixed.live_resampling_plan({**c, 'anchor_seconds': anchor}, p, info)
            require(temporal['trailing_clone_padding_frames'] == 0, f'Window needs forbidden trailing freeze: {c["asset_id"]}')
            temporal['native_time_base'] = mixed.stream(info, 'video')['time_base']
            temporal['primary_video_duration_seconds'] = metadata['duration']
            if c['type'] == 'native_video':
                temporal.pop('anchor_output_seconds')
                temporal.pop('anchor_nearest_output_frame')
        return {**row, 'info': info, 'color': color, 'video_resampling': temporal}
    def inspect_result(row):
        try:
            return inspect(row), None
        except (Error, m.Error, OSError, KeyError, TypeError, ValueError) as error:
            return None, f'{row["cut"]["asset_id"]}: {error}'
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(inspect_result, preliminary))
    failures = [error for _, error in results if error is not None]
    require(not failures, 'Preflight failed: ' + '; '.join(failures))
    checked = [row for row, _ in results]
    m.check_filters([r['color'] for r in checked])
    verify.check_hash(baseline_path, plan['baseline_verification_sha256'], 'Baseline after preflight')
    verify.check_hash(exclusion_path, plan['excluded_ids_sha256'], 'Exclusions after preflight')
    return checked, total


def mux_mp4(source_args, destination, frames):
    verify.run([verify.FFMPEG, '-v', 'error', '-xerror', '-nostdin', '-threads', '2',
                *source_args, '-map', '0:v:0', '-map', '0:a:0', '-t', str(frames / 30), '-c:v', 'copy',
                '-bsf:v', 'setts=time_base=1/90000:pts=N*3000:dts=N*3000:duration=3000',
                '-video_track_timescale', '90000', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                *verify.TAGS, '-map_metadata', '-1', '-movflags', '+faststart', '-n', destination])
    return verify.verify(destination, frames, 1080, 1440, pcm=False, full_decode=True)


def render(plan, plan_path, work, kit, workers=2, execute=False):
    work, kit = Path(work).resolve(), Path(kit).resolve()
    plan_path = Path(plan_path).resolve()
    require(json.loads(plan_path.read_text()) == plan, 'Plan differs from file')
    plan_hash = verify.sha256(plan_path)
    checked, total = validate(plan, work, kit, workers)
    verify.check_hash(plan_path, plan_hash, 'Plan after preflight')
    summary = dict(validated=True, executed=execute, cuts=len(checked), frames=total, duration_seconds=total/30,
                   width=1080, height=1440, kit=str(kit))
    if not execute:
        return {**summary, 'temporal_preflight': [{ 'asset_id': r['cut']['asset_id'], 'video_resampling': r['video_resampling']} for r in checked]}
    work.mkdir(parents=True)
    (kit / 'clips').mkdir(parents=True)
    def prepare(index_row):
        index, row = index_row
        c, p, n = row['cut'], row['path'], row['cut']['frames']
        dest = work / f'{index:03}.mkv'
        cmd = [m.FFMPEG, '-v', 'error', '-xerror', '-nostdin']
        if c['type'] == 'still':
            cmd += ['-loop', '1', '-framerate', '30']
        cmd += ['-i', p]
        audible = c['type'] != 'still' and bool(mixed.stream(row['info'], 'audio'))
        if not audible:
            cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        crop = c['crop_rect']
        temporal = mixed.live_window_filter(c) if c['type'] != 'still' else 'fps=30,'
        vf = (temporal + row['color'] + m.fit_filter(1080, 1920) + ',' +
              f'crop={crop["width"]}:{crop["height"]}:{crop["x"]}:{crop["y"]},scale=1080:1440:flags=lanczos,' +
              f'trim=end_frame={n},setsar=1,settb=1/30,setpts=N,format=yuv420p,sidedata=mode=delete,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited')
        audio_window = f'atrim=start={c["start"]:.12f}:end={c["start"]+n/30:.12f},asetpts=PTS-STARTPTS,' if audible else ''
        af = audio_window + f'aresample=48000,volume={row["gain"]}dB,apad,atrim=end_sample={n*1600},asetpts=N/SR/TB'
        if c['type'] != 'still':
            af += f',afade=t=in:d=0.01,afade=t=out:st={n/30-.01:.12f}:d=0.01'
        if c['type'] == 'still':
            cmd += ['-t', str(n/30)]
        cmd += ['-map', '0:v:0', '-map', '0:a:0' if audible else '1:a:0', '-vf', vf, '-af', af,
                '-r', '30', '-enc_time_base:v', '1/30', '-fps_mode', 'cfr',
                '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-threads', '2', '-bf', '0',
                '-profile:v', 'high', '-level:v', '4.0', '-pix_fmt', 'yuv420p', *verify.TAGS,
                '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', '-map_metadata', '-1', '-n', dest]
        m.run(cmd)
        _, pcm = verify.verify(dest, n, 1080, 1440, full_decode=True)
        clip = kit / 'clips' / f'{index:03}-{c["asset_id"]}.mp4'
        _, audio = mux_mp4(['-i', dest], clip, n)
        packets = verify.video_packets(dest)
        require(packets == verify.video_packets(clip), 'Kit picture packets changed')
        record = {**row['original'], **c, 'segment': str(dest), 'segment_sha256': verify.sha256(dest),
                  'file': clip.relative_to(kit).as_posix(), 'audio_gain_db': row['gain'], 'clip_sha256': verify.sha256(clip), 'fps': 30,
                  'video_resampling': row['video_resampling'], 'pcm': pcm, 'aac_decoded_samples_per_channel': audio['samples_per_channel'],
                  'aac_tail_padding_samples': audio['samples_per_channel'] - n*1600, 'video_packets_preserved': True}
        print(f'Verified cut {index}/{len(checked)}: {c["asset_id"]}', flush=True)
        return record, packets
    with ThreadPoolExecutor(max_workers=workers) as pool:
        prepared = list(pool.map(prepare, enumerate(checked, 1)))
    records, packets, cursor = [], [], 0
    for record, hashes in prepared:
        record.update(timeline_start_frame=cursor, timeline_end_frame=cursor+record['frames'])
        cursor += record['frames']; records.append(record); packets.extend(hashes)
    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{i:03}.mkv'\n" for i in range(1, len(records)+1)))
    reference = kit / 'reference.mp4'
    final, audio = mux_mp4(['-f', 'concat', '-safe', '1', '-auto_convert', '0', '-i', concat], reference, total)
    require(verify.video_packets(reference) == packets, 'Reference picture packets changed')
    for row in checked:
        verify.check_hash(row['path'], row['cut']['source_sha256'], 'Source post render')
    for key, label in [('baseline_verification', 'Baseline'), ('excluded_ids', 'Exclusions')]:
        verify.check_hash(plan[key], plan[key+'_sha256'], label+' post render')
    verify.check_hash(plan_path, plan_hash, 'Plan post render')
    report = {**summary, 'fps': 30, 'cuts': records, 'output': str(reference), 'output_sha256': verify.sha256(reference),
              'plan': str(plan_path), 'plan_sha256': plan_hash, 'baseline_verification': plan['baseline_verification'],
              'baseline_verification_sha256': plan['baseline_verification_sha256'], 'excluded_ids_sha256': plan['excluded_ids_sha256'],
              'video_packets_preserved': True, 'full_decode_verified': True, 'single_picture_encode': True,
              'expected_pcm_samples_per_channel': total*1600, 'decoded_audio_samples_per_channel': audio['samples_per_channel'],
              'aac_tail_padding_samples': audio['samples_per_channel']-total*1600, 'probe': final}
    (work / 'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    timeline = { 'version': 1, 'fps': 30, 'width': 1080, 'height': 1440, 'frames': total, 'reference': 'reference.mp4',
                 'cuts': [{k: c[k] for k in ('file', 'asset_id', 'type', 'frames', 'fps', 'path', 'source_sha256',
                                           'timeline_start_frame', 'timeline_end_frame', 'reason', 'crop_rect', 'active_rect', 'audio_gain_db')}
                          | {k: c[k] for k in ('start', 'anchor_seconds', 'original_still_path', 'original_still_sha256') if k in c} for c in records]}
    (kit / 'timeline.json').write_text(json.dumps(timeline, indent=2)+'\n')
    return {**summary, 'reference_sha256': report['output_sha256'], 'video_packets_preserved': True, 'aac_tail_padding_samples': report['aac_tail_padding_samples']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--kit-dir', type=Path, required=True)
    p.add_argument('--ffmpeg', default=m.FFMPEG)
    p.add_argument('--ffprobe', default=m.FFPROBE)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    m.FFMPEG = verify.FFMPEG = shutil.which(a.ffmpeg or '')
    m.FFPROBE = verify.FFPROBE = shutil.which(a.ffprobe or '')
    if not m.FFMPEG or not m.FFPROBE:
        p.error('ffmpeg and ffprobe required')
    try:
        print(json.dumps(render(json.loads(a.plan.read_text()), a.plan, a.work_dir, a.kit_dir, a.workers, a.execute)))
    except (Error, m.Error, OSError, ValueError, KeyError, TypeError) as e:
        p.exit(1, f'{e}\n')

if __name__ == '__main__':
    main()
