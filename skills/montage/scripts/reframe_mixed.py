#!/usr/bin/env python3
"""Reframe pinned, accepted SDR/PCM montage segments without changing their timing/audio.

Dry-run is the default: validate every cut and destination before any output exists.
Geometry is editorial input in absolute pixels of each finished baseline segment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

TAGS = ['-color_primaries', 'bt709', '-color_trc', 'bt709',
        '-colorspace', 'bt709', '-color_range', 'tv']
FFMPEG = 'ffmpeg'
FFPROBE = 'ffprobe'


class Error(ValueError):
    pass


def run(args):
    result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise Error(f'Command failed: {args[0]}: {result.stderr.decode(errors="replace")[-4000:]}')
    return result.stdout


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def json_probe(path, extra=()):
    return json.loads(run([FFPROBE, '-v', 'error', '-threads', '1', *extra, '-of', 'json', path]))


def stream(info, kind):
    return next((s for s in info['streams'] if s['codec_type'] == kind), {})


def pcm_identity(path):
    # Stream samples to a digest, retaining neither media nor huge byte buffers.
    proc = subprocess.Popen([FFMPEG, '-v', 'error', '-nostdin', '-threads', '2',
                             '-i', str(path), '-map', '0:a:0', '-c:a', 'pcm_s16le',
                             '-f', 's16le', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: proc.stdout.read(1024 * 1024), b''):
        digest.update(block)
        size += len(block)
    err = proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    if proc.wait():
        raise Error(f'Audio decoding failed: {path}: {err.decode(errors="replace")[-2000:]}')
    return {'sha256': digest.hexdigest(), 'bytes': size, 'samples_per_channel': size // 4}


def video_packets(path):
    return [p['data_hash'] for p in json_probe(path, [
        '-select_streams', 'v:0', '-show_packets', '-show_data_hash', 'sha256',
        '-show_entries', 'packet=data_hash'])['packets']]


def verify(path, frames, width, height, pcm=True, full_decode=False, strict_rate=True):
    info = json_probe(path, ['-count_frames', '-show_streams', '-show_format'])
    v, a = stream(info, 'video'), stream(info, 'audio')
    expected = {'codec_name': 'h264', 'width': width, 'height': height,
                'pix_fmt': 'yuv420p', 'sample_aspect_ratio': '1:1',
                'profile': 'High', 'level': 40, 'has_b_frames': 0,
                'color_primaries': 'bt709', 'color_transfer': 'bt709',
                'color_space': 'bt709', 'color_range': 'tv'}
    wrong = {k: v.get(k) for k, value in expected.items() if v.get(k) != value}
    if wrong:
        raise Error(f'Incompatible video parameters: {path}: {wrong}')
    if int(v.get('nb_read_frames', -1)) != frames or (strict_rate and (v.get('r_frame_rate') != '30/1' or v.get('avg_frame_rate') != '30/1')):
        raise Error(f'Frame count/rate mismatch: {path}')
    if v.get('side_data_list') or v.get('tags', {}).get('rotate'):
        raise Error(f'Inherited video side data/rotation: {path}')
    decoded = json_probe(path, ['-select_streams', 'v:0', '-show_frames',
                               '-show_entries', 'frame=best_effort_timestamp_time,side_data_list'])['frames']
    # Matroska rounds the accepted 30fps timestamps to milliseconds. MP4 final
    # timestamps are checked strictly below against the 90kHz track clock.
    tolerance = .0011 if pcm else .000012
    if len(decoded) != frames or any(
            abs(float(f.get('best_effort_timestamp_time', '-999')) - i / 30) > tolerance
            for i, f in enumerate(decoded)):
        raise Error(f'Non-CFR/nonzero-origin frame timestamps: {path}')
    for f in decoded:
        for side in f.get('side_data_list', []):
            if any(word in side.get('side_data_type', '').lower()
                   for word in ('mastering', 'content light', 'dovi', 'dolby', 'hdr', 'display matrix')):
                raise Error(f'Inherited HDR/rotation frame side data: {path}')
    if a.get('sample_rate') != '48000' or a.get('channels') != 2:
        raise Error(f'Audio format mismatch: {path}')
    if a.get('codec_name') != ('pcm_s16le' if pcm else 'aac'):
        raise Error(f'Audio codec mismatch: {path}')
    audio = pcm_identity(path)
    target = frames * 1600
    if audio['bytes'] % 4 or (audio['samples_per_channel'] != target if pcm else
                              not target <= audio['samples_per_channel'] <= target + 1023):
        raise Error(f'Audio sample count mismatch: {path}: {audio["samples_per_channel"]}, expected {target}')
    if not pcm and (v.get('time_base') != '1/90000' or
                    int(v.get('duration_ts', -1)) != frames * 3000):
        raise Error(f'Final video duration/clock mismatch: {path}')
    if full_decode:
        run([FFMPEG, '-v', 'error', '-xerror', '-nostdin', '-threads', '2', '-i', path,
             '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
    return info, audio


def absolute_file(value, label):
    if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
        raise Error(f'{label} must be an absolute existing file')
    return Path(value).resolve()


def check_hash(path, expected, label):
    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected) or sha256(path) != expected:
        raise Error(f'{label} SHA-256 mismatch: {path}')


def rect(value, label):
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}:
        raise Error(f'{label} must have x/y/width/height')
    if any(type(v) is not int or v % 2 for v in value.values()) or any(value[k] < 0 for k in ('x', 'y')) or any(value[k] <= 0 for k in ('width', 'height')):
        raise Error(f'{label} needs even integer coordinates and positive even dimensions')
    return value


def contained(inner, outer):
    return (inner['x'] >= outer['x'] and inner['y'] >= outer['y'] and
            inner['x'] + inner['width'] <= outer['x'] + outer['width'] and
            inner['y'] + inner['height'] <= outer['y'] + outer['height'])


def destinations(work, output, protected):
    if work.exists() or output.exists() or work.is_symlink() or output.is_symlink():
        raise Error('Work directory and output must be fresh paths')
    if output.suffix.lower() != '.mp4' or work == output or work in output.parents or output in work.parents:
        raise Error('Use separate fresh work directory and MP4 output paths')
    for destination in (work, output):
        if any((p / '.git').exists() for p in (destination, *destination.parents)):
            raise Error('Keep media outside Git repositories')
        if any(destination == p or destination in p.parents for p in protected):
            raise Error('Destination would contain or overwrite a protected input')


def validate(plan, work, output, workers=2):
    if not isinstance(plan, dict) or type(plan.get('version')) is not int or plan.get('version') != 1 or plan.get('fps') != 30:
        raise Error('Expected plan version 1 and fps 30')
    width, height = plan.get('width'), plan.get('height')
    if any(type(v) is not int or v <= 0 or v % 2 for v in (width, height)):
        raise Error('Output dimensions must be positive even integers')
    # Level 4.0 has a macroblock limit of 8192/frame and 245760/second.
    macroblocks = ((width + 15) // 16) * ((height + 15) // 16)
    if macroblocks * 30 > 245760:
        raise Error('Output dimensions exceed H264 level4.0 at30fps')
    if type(workers) is not int or not 1 <= workers <= 2:
        raise Error('workers must be 1 or 2 (two encoder threads each)')
    baseline_path = absolute_file(plan.get('baseline_verification'), 'baseline_verification')
    check_hash(baseline_path, plan.get('baseline_verification_sha256'), 'Baseline')
    baseline = json.loads(baseline_path.read_text())
    baseline_cuts = baseline['cuts']
    originals = {c['asset_id']: c for c in baseline_cuts}
    if len(originals) != len(baseline_cuts) or baseline.get('fps') != 30:
        raise Error('Baseline asset IDs must be unique and fps30')
    exclusion_path = absolute_file(plan.get('excluded_ids'), 'excluded_ids')
    exclusion_digest = sha256(exclusion_path)
    exclusions = json.loads(exclusion_path.read_text())
    if isinstance(exclusions, dict):
        exclusions = exclusions.get('excluded_ids')
    if not isinstance(exclusions, list) or any(not isinstance(x, str) for x in exclusions) or len(set(exclusions)) != len(exclusions):
        raise Error('Exclusions must be a JSON list or {excluded_ids:[unique strings]}')
    if 'excluded_ids_sha256' in plan:
        check_hash(exclusion_path, plan['excluded_ids_sha256'], 'Exclusions')
    cuts = plan.get('cuts')
    if not isinstance(cuts, list) or not cuts or any(not isinstance(c, dict) for c in cuts):
        raise Error('cuts must be a nonempty list')
    ids = [c.get('asset_id') for c in cuts]
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise Error('Cut asset IDs must be nonempty and unique')
    removed = plan.get('removed_ids', [])
    if not isinstance(removed, list) or any(not isinstance(x, str) for x in removed) or len(set(removed)) != len(removed):
        raise Error('removed_ids must be unique strings')
    if set(ids) & set(exclusions):
        raise Error('Selected asset is on the exclusion holdlist')
    if set(ids) != set(originals) - set(removed) or not set(removed) <= set(originals):
        raise Error('Selected/removed IDs must exactly partition the baseline')
    ordered = [c['asset_id'] for c in baseline_cuts if c['asset_id'] in ids]
    exception = plan.get('opener_exception')
    if exception:
        if not isinstance(exception, dict) or exception.get('asset_id') not in ordered or not isinstance(exception.get('reason'), str) or not exception['reason'].strip():
            raise Error('opener_exception needs a kept asset_id and reason')
        ordered.remove(exception['asset_id'])
        ordered.insert(0, exception['asset_id'])
    if ids != ordered:
        raise Error('Body chronology/order changed from baseline without a declared opener exception')
    total = 0
    prepared = []
    protected = [baseline_path, exclusion_path]
    for cut in cuts:
        original = originals[cut['asset_id']]
        for key in ('type', 'frames', 'segment_sha256'):
            if cut.get(key) != original.get(key):
                raise Error(f'Baseline {key} mismatch for {cut["asset_id"]}')
        if type(cut['frames']) is not int or cut['frames'] <= 0:
            raise Error('Cut frames must be positive integers')
        path = absolute_file(cut.get('segment'), 'segment')
        if path != absolute_file(original.get('segment'), 'baseline segment'):
            raise Error(f'Baseline segment identity mismatch for {cut["asset_id"]}')
        active = rect(cut.get('active_rect'), 'active_rect')
        crop = rect(cut.get('crop_rect'), 'crop_rect')
        if not contained(crop, active):
            raise Error(f'Crop outside active image for {cut["asset_id"]}')
        if not isinstance(cut.get('framing_reason'), str) or not cut['framing_reason'].strip():
            raise Error('Every cut needs framing_reason')
        total += cut['frames']
        protected.append(path)
        prepared.append({'cut': cut, 'original': original, 'path': path})
    if plan.get('expected_frames', total) != total or plan.get('expected_cuts', len(cuts)) != len(cuts):
        raise Error('Expected timeline frame/cut total mismatch')
    destinations(work, output, protected)

    def inspect(row):
        cut, path = row['cut'], row['path']
        check_hash(path, cut['segment_sha256'], 'Prepared segment')
        info = json_probe(path, ['-show_streams'])
        v = stream(info, 'video')
        full = {'x': 0, 'y': 0, 'width': v.get('width', 0), 'height': v.get('height', 0)}
        if not contained(cut['active_rect'], full):
            raise Error(f'Active rectangle outside segment: {cut["asset_id"]}')
        _, audio = verify(path, cut['frames'], full['width'], full['height'], strict_rate=False)
        return {**row, 'audio': audio, 'source_dimensions': [full['width'], full['height']]}

    # Await all checks before creating even a log or destination folder.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        checked = list(pool.map(inspect, prepared))
    check_hash(baseline_path, plan['baseline_verification_sha256'], 'Baseline after-preflight')
    check_hash(exclusion_path, exclusion_digest, 'Exclusions after-preflight')
    return checked, baseline_path, exclusion_path, total


def render(plan, plan_path, work, output, workers=2, execute=False):
    work, output = Path(work).resolve(), Path(output).resolve()
    plan_digest = sha256(plan_path)
    if json.loads(Path(plan_path).read_text()) != plan:
        raise Error('Loaded plan differs from pinned plan file')
    checked, baseline_path, exclusion_path, total = validate(plan, work, output, workers)
    check_hash(plan_path, plan_digest, 'Plan after-preflight')
    summary = {'validated': True, 'executed': execute, 'cuts': len(checked),
               'frames': total, 'duration_seconds': total / 30,
               'width': plan['width'], 'height': plan['height'], 'output': str(output)}
    if not execute:
        return summary
    check_hash(plan_path, plan_digest, 'Plan before-render')
    check_hash(baseline_path, plan['baseline_verification_sha256'], 'Baseline before-render')
    exclusion_digest = sha256(exclusion_path)
    work.mkdir(parents=True, exist_ok=False)

    def prepare(index_row):
        index, row = index_row
        cut, path = row['cut'], row['path']
        dest = work / f'{index:03}.mkv'
        c = cut['crop_rect']
        vf = (f'crop={c["width"]}:{c["height"]}:{c["x"]}:{c["y"]},'
              f'scale={plan["width"]}:{plan["height"]}:flags=lanczos,setsar=1,'
              'settb=1/30,setpts=N,format=yuv420p,sidedata=mode=delete')
        run([FFMPEG, '-v', 'error', '-xerror', '-nostdin', '-threads', '2',
             '-filter_threads', '1', '-i', path, '-map', '0:v:0', '-map', '0:a:0',
             '-vf', vf, '-r', '30', '-enc_time_base:v', '1/30', '-fps_mode', 'cfr', '-c:v', 'libx264', '-crf', '18',
             '-preset', 'medium', '-threads', '2', '-bf', '0', '-profile:v', 'high',
             '-level:v', '4.0', '-pix_fmt', 'yuv420p', *TAGS, '-c:a', 'copy',
             '-map_metadata', '-1', '-n', dest])
        _, audio = verify(dest, cut['frames'], plan['width'], plan['height'])
        if audio != row['audio']:
            raise Error(f'PCM changed during reframe: {cut["asset_id"]}')
        # Preserve all baseline provenance but distinguish the finished input
        # identity from the newly encoded segment identity.
        record = {**row['original'], **cut, 'baseline_segment': str(path),
                  'baseline_segment_sha256': cut['segment_sha256'],
                  'segment': str(dest), 'segment_sha256': sha256(dest),
                  'pcm': audio, 'pcm_identical_to_baseline': True,
                  'source_segment_dimensions': row['source_dimensions'],
                  'scale_x': plan['width'] / c['width'],
                  'scale_y': plan['height'] / c['height'],
                  'aspect_ratio_adjustment': float(Fraction(plan['width'], plan['height']) / Fraction(c['width'], c['height']))}
        print(f'Verified cut {index}/{len(checked)}: {cut["asset_id"]}', flush=True)
        return record, video_packets(dest)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        prepared = list(pool.map(prepare, enumerate(checked, 1)))
    cursor, timeline, packet_hashes = 0, [], []
    for record, packets in prepared:
        record.update(timeline_start_frame=cursor, timeline_end_frame=cursor + record['frames'])
        cursor += record['frames']
        timeline.append(record)
        packet_hashes.extend(packets)
    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{Path(c['segment']).name}'\n" for c in timeline))
    output.parent.mkdir(parents=True, exist_ok=True)
    run([FFMPEG, '-v', 'error', '-xerror', '-nostdin', '-threads', '2',
         '-f', 'concat', '-safe', '1', '-auto_convert', '0', '-i', concat,
         '-map', '0:v:0', '-map', '0:a:0', '-t', str(total / 30), '-c:v', 'copy',
         '-bsf:v', 'setts=time_base=1/90000:pts=N*3000:dts=N*3000:duration=3000',
         '-video_track_timescale', '90000', '-c:a', 'aac', '-b:a', '192k',
         '-ar', '48000', '-ac', '2', *TAGS, '-map_metadata', '-1',
         '-movflags', '+faststart', '-n', output])
    final, audio = verify(output, total, plan['width'], plan['height'], pcm=False, full_decode=True)
    if video_packets(output) != packet_hashes:
        raise Error('Final concat changed prepared video packets')
    check_hash(baseline_path, plan['baseline_verification_sha256'], 'Baseline post-render')
    check_hash(plan_path, plan_digest, 'Plan post-render')
    check_hash(exclusion_path, exclusion_digest, 'Exclusions post-render')
    for row in checked:
        check_hash(row['path'], row['cut']['segment_sha256'], 'Segment post-render')
    report = {**summary, 'fps': 30, 'cuts': timeline, 'output_sha256': sha256(output),
              'plan': str(plan_path), 'plan_sha256': plan_digest,
              'baseline_verification': str(baseline_path),
              'baseline_verification_sha256': plan['baseline_verification_sha256'],
              'excluded_ids': str(exclusion_path), 'excluded_ids_sha256': exclusion_digest,
              'opener_exception': plan.get('opener_exception'), 'removed_ids': plan.get('removed_ids', []),
              'expected_frames': total, 'expected_cuts': len(checked),
              'body_order_and_timing_preserved': True, 'video_packets_preserved': True,
              'per_frame_timing_verified': True, 'prepared_segment_hashes_reverified': True,
              'expected_pcm_samples_per_channel': total * 1600,
              'decoded_audio_samples_per_channel': audio['samples_per_channel'],
              'aac_tail_padding_samples': audio['samples_per_channel'] - total * 1600,
              'full_decode_verified': True, 'probe': final}
    (work / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return {**summary, 'video_packets_preserved': True, 'output_sha256': report['output_sha256']}


def main():
    global FFMPEG, FFPROBE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffmpeg', default=FFMPEG)
    parser.add_argument('--ffprobe', default=FFPROBE)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    FFMPEG, FFPROBE = shutil.which(args.ffmpeg), shutil.which(args.ffprobe)
    if not FFMPEG or not FFPROBE:
        parser.error('ffmpeg and ffprobe are required')
    try:
        plan_path = args.plan.resolve()
        result = render(json.loads(plan_path.read_text()), plan_path, args.work_dir,
                        args.output, args.workers, args.execute)
    except (Error, OSError, KeyError, TypeError, json.JSONDecodeError) as e:
        parser.exit(1, f'{e}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
