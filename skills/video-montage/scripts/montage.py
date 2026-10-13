#!/usr/bin/env python3
"""Prepare bounded contact sheets, validate a human edit, and render a local montage."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.webm', '.mts', '.m2ts', '.mpg', '.mpeg', '.3gp'}
FFMPEG = shutil.which(os.environ.get('MONTAGE_FFMPEG', 'ffmpeg'))
FFPROBE = shutil.which('ffprobe')
# A tiny built-in bitmap font keeps timestamp labels independent of drawtext/Pillow.
FONT = dict(zip('0123456789:.C', [
    '111101101101111', '010110010010111', '111001111100111',
    '111001111001111', '101101111001001', '111100111001111',
    '111100111101111', '111001010010010', '111101111101111',
    '111101111001111', '000010000010000', '000000000000010',
    '111100100100111']))


class Error(Exception):
    pass


def run(argv, binary=False):
    result = subprocess.run([str(x) for x in argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode(errors='replace').strip().splitlines()
        raise Error(f'{Path(argv[0]).name} failed: ' + '\n'.join(detail[-5:]))
    return result.stdout if binary else result.stdout.decode()


def probe(path):
    data = json.loads(run([FFPROBE, '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', path]))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'
                  and not s.get('disposition', {}).get('attached_pic')), None)
    if not video:
        raise Error(f'No video stream: {path}')
    duration = float(video.get('duration', data.get('format', {}).get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise Error(f'Invalid video duration: {path}')
    rotation = video.get('tags', {}).get('rotate', 0)
    for side in video.get('side_data_list', []):
        rotation = side.get('rotation', rotation)
    fps = video.get('avg_frame_rate', '0/1').split('/')
    rate = float(fps[0]) / float(fps[1]) if len(fps) == 2 and float(fps[1]) else 30
    return {'duration': duration, 'width': video['width'], 'height': video['height'],
            'rotation': float(rotation), 'has_audio': any(s['codec_type'] == 'audio' for s in data['streams']),
            'frame_rate': rate if rate > 0 else 30, 'streams': data['streams']}


def color_filter(metadata, source):
    """Convert the tested BT.2020 HLG base layer; refuse other explicit HDR."""
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video'
                 and not s.get('disposition', {}).get('attached_pic'))
    transfer = video.get('color_transfer', 'unknown')
    sides = video.get('side_data_list', [])
    dovi = [s for s in sides if s.get('side_data_type') == 'DOVI configuration record']
    if transfer == 'arib-std-b67':
        if (video.get('color_primaries') != 'bt2020'
                or video.get('color_space') != 'bt2020nc'
                or video.get('color_range') != 'tv'
                or any(s.get('dv_profile') != 8 or s.get('dv_bl_signal_compatibility_id') != 4
                       for s in dovi)):
            raise Error(f'Unsupported HLG color metadata: {source}. '
                        'Expected limited-range BT.2020 / BT.2020nc, with an HLG-compatible base layer.')
        # Keep chroma: desat>0 can misidentify colored pixels as highlights in
        # this linear RGB path (FFmpeg 7.1), whitening blue clothes and skies.
        return ('zscale=pin=bt2020:tin=arib-std-b67:min=bt2020nc:rin=limited:t=linear:npl=400,'
                'format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0:peak=2.5,'
                'zscale=t=bt709:m=bt709:r=limited,format=yuv420p,')
    hdr_side = any(any(marker in s.get('side_data_type', '').lower()
                       for marker in ('dovi', 'dolby', 'mastering display', 'content light', 'hdr'))
                   for s in sides)
    sdr_transfers = {'unknown', 'unspecified', 'bt709', 'gamma22', 'gamma28',
                     'smpte170m', 'smpte240m', 'iec61966-2-1', 'bt2020-10', 'bt2020-12'}
    if transfer not in sdr_transfers or hdr_side:
        raise Error(f'Unsupported HDR transfer/metadata ({transfer}): {source}. '
                    'Only limited-range BT.2020 HLG is supported; supply a visually checked SDR conversion.')
    return ''


def check_filters(color_filters):
    required = {'sidedata'}
    if any(color_filters):
        required.update({'zscale', 'tonemap'})
    available = {line.split()[1] for line in run([FFMPEG, '-hide_banner', '-filters']).splitlines()
                 if len(line.split()) >= 3 and '->' in line.split()[2]}
    missing = required - available
    if missing:
        raise Error(f'FFmpeg lacks required filters: {", ".join(sorted(missing))}. '
                    'Use an FFmpeg build with libzimg (zscale) and tonemap; '
                    'set MONTAGE_FFMPEG=/absolute/path/to/ffmpeg. No output has been written.')


def identity(path):
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Error(f'{name} must be a finite number')
    if positive and value <= 0:
        raise Error(f'{name} must be greater than zero')
    return float(value)


def samples(duration, interval, fps):
    last = max(0, duration - 1 / fps)
    count = int(math.floor(last / interval)) + 1
    for i in range(count):
        yield i * interval
    if last - (count - 1) * interval > 0.001:
        yield last


def stamp(seconds):
    millis = round(seconds * 1000)
    return f'{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02}.{millis % 1000:03}'


def label(canvas, width, x, y, text):
    for char in text:
        bitmap = FONT.get(char, '000000000000000')
        for row in range(5):
            for col in range(3):
                if bitmap[row * 3 + col] == '1':
                    for dy in range(3):
                        offset = ((y + row * 3 + dy) * width + x + col * 3) * 3
                        canvas[offset:offset + 9] = b'\xff' * 9
        x += 12


def fit_filter(width, height):
    # dar includes sample aspect ratio after FFmpeg's automatic display rotation.
    # Choose square-pixel dimensions first; resetting SAR after coded-size scaling
    # would stretch anamorphic footage. Round down to even sizes for H.264.
    return (f"scale=w='max(2,trunc(min({width},{height}*dar)/2)*2)':"
            f"h='max(2,trunc(min({height},{width}/dar)/2)*2)',setsar=1,"
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2')


def sheets(source, folder, clip_id, metadata, interval):
    """Hold only one 16-cell page and one decoded frame in memory at a time."""
    width, height, cell_h = 1280, 848, 212
    page, cells, canvas, mapping = 1, 0, None, []
    def save():
        filename = f'{clip_id}-page-{page:04}.jpg'
        header = f'P6\n{width} {height}\n255\n'.encode()
        # Feed PPM through stdin; no transient frame files or giant image sequences.
        result = subprocess.run([FFMPEG, '-v', 'error', '-nostdin', '-f', 'image2pipe',
                                 '-vcodec', 'ppm', '-i', 'pipe:0', '-frames:v', '1',
                                 '-q:v', '3', '-n', str(folder / filename)],
                                input=header + canvas, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise Error(result.stderr.decode(errors='replace').strip())
    for timestamp in samples(metadata['duration'], interval, metadata['frame_rate']):
        if cells == 0:
            canvas = bytearray(width * height * 3)
        raw = run([FFMPEG, '-v', 'error', '-nostdin', '-ss', f'{timestamp:.9f}',
                   '-i', source, '-map', '0:v:0', '-frames:v', '1', '-vf',
                   color_filter(metadata, source) + fit_filter(320, 180) + ',sidedata=mode=delete',
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], binary=True)
        if len(raw) != 320 * 180 * 3:
            raise Error(f'Could not decode {source} at {stamp(timestamp)}')
        x, y = (cells % 4) * 320, (cells // 4) * cell_h
        for row in range(180):
            offset = ((y + row) * width + x) * 3
            canvas[offset:offset + 960] = raw[row * 960:(row + 1) * 960]
        label(canvas, width, x + 8, y + 187, clip_id.upper() + ' ' + stamp(timestamp))
        mapping.append({'page': f'{clip_id}-page-{page:04}.jpg', 'cell': cells + 1,
                        'timestamp': timestamp, 'label': stamp(timestamp)})
        cells += 1
        if cells == 16:
            save()
            page, cells = page + 1, 0
    if cells:
        save()
    return mapping


def prepare(args):
    source, work = args.input.expanduser().resolve(), args.work_dir.expanduser().resolve()
    if not source.is_dir():
        raise Error('Input must be a directory')
    if work == source or source in work.parents:
        raise Error('Work directory must be outside the input directory')
    if work.exists():
        raise Error('Work directory already exists; choose a new directory')
    interval = number(args.interval, 'interval', True)
    prefs = {'min_duration': number(args.min_duration, 'min-duration', True),
             'normal_max': number(args.normal_max, 'normal-max', True),
             'max_duration': number(args.max_duration, 'max-duration', True)}
    if not prefs['min_duration'] <= prefs['normal_max'] <= prefs['max_duration']:
        raise Error('Require min-duration <= normal-max <= max-duration')
    paths = sorted({p.resolve() for p in source.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS})
    if not paths:
        raise Error('No supported video files found')
    # Fail unsupported HDR or missing conversion capabilities before creating
    # a work directory or writing even the first contact sheet.
    inspected = [(path, probe(path), identity(path)) for path in paths]
    check_filters([color_filter(metadata, path) for path, metadata, _ in inspected])
    work.mkdir(parents=True, exist_ok=False)
    contacts = work / 'contact-sheets'
    contacts.mkdir()
    manifest = {'version': 1, 'input': str(source), 'interval': interval, 'preferences': prefs, 'clips': []}
    for index, (path, metadata, original) in enumerate(inspected, 1):
        clip_id = f'c{index:04}'
        clip = {'clip_id': clip_id, 'path': str(path), **original,
                **{key: value for key, value in metadata.items() if key != 'streams'}}
        clip['samples'] = sheets(path, contacts, clip_id, metadata, interval)
        if identity(path) != original:
            raise Error(f'Source changed while preparing: {path}')
        manifest['clips'].append(clip)
        print(f'{clip_id}: {path.name}, {metadata["duration"]:.3f}s, {len(clip["samples"])} samples', flush=True)
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (work / 'edit.json').write_text(json.dumps({'selections': []}, indent=2) + '\n')
    print(f'Manifest and edit template: {work}')


def validate(work, edit_path):
    manifest = json.loads((work / 'manifest.json').read_text())
    if not isinstance(manifest, dict):
        raise Error('manifest.json must contain a JSON object')
    if manifest.get('version') != 1:
        raise Error('Unsupported manifest version')
    clips = {c['clip_id']: c for c in manifest['clips']}
    prefs = manifest['preferences']
    for key in ('min_duration', 'normal_max', 'max_duration'):
        number(prefs[key], f'manifest {key}', True)
    if not prefs['min_duration'] <= prefs['normal_max'] <= prefs['max_duration']:
        raise Error('Invalid manifest duration preferences')
    for clip in clips.values():
        path = Path(clip['path'])
        if not path.is_file() or identity(path) != {k: clip[k] for k in ('size', 'mtime_ns')}:
            raise Error(f'Source missing or changed: {path}')
    edit = json.loads(edit_path.read_text())
    if not isinstance(edit, dict):
        raise Error('edit.json must contain a JSON object')
    selections = edit.get('selections')
    if not isinstance(selections, list) or not selections:
        raise Error('edit.json needs a nonempty selections list')
    ranges, total = {}, 0.0
    for index, item in enumerate(selections, 1):
        if not isinstance(item, dict) or not isinstance(item.get('clip_id'), str) or item['clip_id'] not in clips:
            raise Error(f'Selection {index}: unknown clip_id')
        start = number(item.get('start'), f'Selection {index} start')
        end = number(item.get('end'), f'Selection {index} end')
        reason = item.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise Error(f'Selection {index}: reason must be nonempty text')
        if 'extended' in item and not isinstance(item['extended'], bool):
            raise Error(f'Selection {index}: extended must be boolean')
        length = end - start
        if start < 0 or end > clips[item['clip_id']]['duration'] or end <= start:
            raise Error(f'Selection {index}: range is outside source bounds')
        if length < prefs['min_duration'] - 1e-8 or length > prefs['max_duration'] + 1e-8:
            raise Error(f'Selection {index}: duration must be {prefs["min_duration"]}–{prefs["max_duration"]} seconds')
        if length > prefs['normal_max'] + 1e-8 and item.get('extended') is not True:
            raise Error(f'Selection {index}: longer selections require extended: true and a reason')
        for old_start, old_end in ranges.setdefault(item['clip_id'], []):
            if start < old_end and end > old_start:
                raise Error(f'Selection {index}: duplicate or overlapping source range')
        ranges[item['clip_id']].append((start, end))
        total += length
    if 'target_duration' in edit:
        target = number(edit['target_duration'], 'target_duration', True)
        print(f'Target {target:.3f}s; selected {total:.3f}s (difference {total - target:+.3f}s)')
    return manifest, selections, total


def render(args):
    work = args.work_dir.expanduser().resolve()
    edit = (args.edit or work / 'edit.json').expanduser().resolve()
    manifest, selections, total = validate(work, edit)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise Error('Output already exists; refusing to overwrite')
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        raise Error('Width and height must be positive even integers')
    fps = number(args.fps, 'fps', True)
    gain = number(args.music_gain, 'music-gain')
    if gain < 0 or gain > 1:
        raise Error('music-gain must be between zero and one')
    clips = {c['clip_id']: c for c in manifest['clips']}
    if any(output == Path(c['path']) for c in clips.values()):
        raise Error('Output cannot be an input source')
    music = args.music.expanduser().resolve() if args.music else None
    if music and (not music.is_file() or output == music):
        raise Error('Music must be an existing local file, distinct from output')
    color_filters = {item['clip_id']: color_filter(probe(clips[item['clip_id']]['path']),
                                                  clips[item['clip_id']]['path'])
                     for item in selections}
    check_filters(color_filters.values())
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.montage-', dir=output.parent) as temporary:
        temp = Path(temporary)
        segment_paths = []
        for index, selection in enumerate(selections):
            clip = clips[selection['clip_id']]
            length = selection['end'] - selection['start']
            segment = temp / f'segment-{index:05}.mp4'
            cmd = [FFMPEG, '-v', 'error', '-nostdin', '-ss', str(selection['start']), '-i', clip['path']]
            audible = clip['has_audio'] and args.audio == 'keep'
            if not audible:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            if color_filters[selection['clip_id']]:
                cmd += ['-color_primaries', 'bt709', '-color_trc', 'bt709',
                        '-colorspace', 'bt709', '-color_range', 'tv']
            cmd += ['-map', '0:v:0', '-map', '0:a:0' if audible else '1:a:0', '-t', str(length),
                    '-vf', color_filters[selection['clip_id']] + fit_filter(args.width, args.height)
                    + f',fps={fps},sidedata=mode=delete',
                    '-af', 'aresample=48000,apad', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                    '-map_metadata', '-1', '-movflags', '+faststart', '-n', segment]
            run(cmd)
            segment_paths.append(segment)
        concat = temp / 'concat.txt'
        concat.write_text(''.join(f"file '{p.name}'\n" for p in segment_paths))
        joined = temp / 'joined.mp4'
        run([FFMPEG, '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-i', concat,
             '-c', 'copy', '-movflags', '+faststart', '-n', joined])
        final = joined
        if music:
            final = temp / 'final.mp4'
            run([FFMPEG, '-v', 'error', '-nostdin', '-i', joined, '-stream_loop', '-1', '-i', music,
                 '-filter_complex', f'[1:a]aresample=48000,volume={gain}[music];'
                 '[0:a][music]amix=inputs=2:duration=first:normalize=0[a]',
                 '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-ar', '48000',
                 '-ac', '2', '-movflags', '+faststart', '-n', final])
        info = probe(final)
        # link() publishes a complete file atomically and fails if another writer won the name.
        os.link(final, output)
    summary = {key: info[key] for key in ('duration', 'width', 'height', 'has_audio')}
    summary['streams'] = [{key: s.get(key) for key in ('codec_type', 'codec_name', 'sample_rate', 'channels', 'pix_fmt')} for s in info['streams']]
    print(f'Rendered {output}\n' + json.dumps(summary, indent=2))
    print('Technical export verification only; watch the full output before sharing.')


def review(args):
    source = args.input.expanduser().resolve()
    folder = args.work_dir.expanduser().resolve()
    if folder.exists():
        raise Error('Review directory already exists; choose a new directory')
    metadata = probe(source)
    interval = number(args.interval, 'interval', True)
    check_filters([color_filter(metadata, source)])
    folder.mkdir(parents=True, exist_ok=False)
    mapping = sheets(source, folder, 'c0001', metadata, interval)
    (folder / 'review.json').write_text(json.dumps({'path': str(source), 'samples': mapping}, indent=2) + '\n')
    print(f'Review contact sheets: {folder}. These do not replace watching the full output.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare', help='Discover videos and sample their entire duration into labelled 4x4 pages')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--work-dir', type=Path, required=True, help='New directory outside input')
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--min-duration', type=float, default=0.8, help='Minimum selection length in seconds (default: 0.8)')
    p.add_argument('--normal-max', type=float, default=1.0, help='Preferred maximum; longer selections need extended: true (default: 1.0)')
    p.add_argument('--max-duration', type=float, default=2.0, help='Strict selection maximum in seconds, including extended cuts (default: 2.0)')
    p.set_defaults(action=prepare)
    p = commands.add_parser('validate', help='Check manual edit selections and unchanged sources')
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--edit', type=Path)
    p.set_defaults(action=lambda a: print('Valid edit: %.3fs selected' % validate(a.work_dir.expanduser().resolve(), (a.edit or a.work_dir / 'edit.json').expanduser().resolve())[2]))
    p = commands.add_parser('render', help='Validate and render normalized H.264/AAC montage without overwriting')
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--edit', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p.add_argument('--fps', type=float, default=30)
    p.add_argument('--audio', choices=('keep', 'mute'), default='keep')
    p.add_argument('--music', type=Path, help='Optional local audio file; looped and mixed')
    p.add_argument('--music-gain', type=float, default=0.15)
    p.set_defaults(action=render)
    p = commands.add_parser('review', help='Create labelled contact sheets from a final export')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--interval', type=float, default=1)
    p.set_defaults(action=review)
    args = parser.parse_args()
    try:
        if not FFMPEG or not FFPROBE:
            raise Error('ffmpeg and ffprobe must be installed and available on PATH; '
                        'MONTAGE_FFMPEG can select an alternate ffmpeg executable')
        args.action(args)
    except (Error, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
