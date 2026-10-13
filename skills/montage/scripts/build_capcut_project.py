#!/usr/bin/env python3
"""Guarded CapCut 8.3 draft update. Dry run by default; requires a local UI seed."""
import argparse
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

SCHEMA = (360000, '163.0.0')

def require(ok, message):
    if not ok:
        raise ValueError(message)

def read(path):
    require(path.is_file() and not path.is_symlink(), f'Missing or symlinked JSON: {path}')
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f'Expected JSON object: {path}')
    return value

def closed():
    result = subprocess.run(['pgrep', '-x', 'CapCut'], capture_output=True)
    require(result.returncode == 1, 'Close CapCut; process detection must succeed before proceeding.')

def uid():
    return str(uuid.uuid4()).upper()

def schema(draft):
    require((draft.get('version'), draft.get('new_version')) == SCHEMA,
            'Unsupported/encrypted draft schema; use the clip-kit UI workflow.')
    require(isinstance(draft.get('materials'), dict) and isinstance(draft.get('tracks'), list),
            'Unsupported materials/tracks schema.')
    require(isinstance(draft.get('canvas_config'), dict), 'Missing canvas config.')
    require(all(isinstance(vals, list) and all(isinstance(m, dict) and isinstance(m.get('id'), str) for m in vals)
                for vals in draft['materials'].values()), 'Unsupported material collections.')
    ids = [m['id'] for vals in draft['materials'].values() for m in vals]
    require(len(ids) == len(set(ids)), 'Duplicate existing material IDs.')

def neutral_seed(seed, segment, width, height):
    # Exact known-neutral defaults: unknown finishing fields are rejected, never erased.
    neutral = read(Path(__file__).resolve().parent.parent / 'references/capcut-neutral-seed.json')
    def matches(actual, expected, variable, label):
        fixed = {k: v for k, v in actual.items() if k not in variable}
        require(fixed == expected, f'Nonneutral or unsupported {label}; create a fresh neutral UI seed.')
    matches(seed['tracks'][0], neutral['track'], {'id', 'segments', 'name'}, 'track')
    matches(segment, neutral['segment'],
            {'id', 'material_id', 'extra_material_refs', 'source_timerange', 'target_timerange'}, 'segment')
    materials = {m['id']: (category, m) for category, values in seed['materials'].items() for m in values}
    require(segment['material_id'] in materials and materials[segment['material_id']][0] == 'videos',
            'Missing seed video material.')
    video = materials[segment['material_id']][1]
    matches(video, neutral['video'],
            {'id', 'duration', 'path', 'material_name', 'local_material_id', 'width', 'height', 'has_audio'}, 'video')
    require(video.get('width') == width and video.get('height') == height,
            'Seed media canvas differs; seed with a corrected kit clip at the requested canvas.')
    require(type(video.get('has_audio')) is bool, 'Unsupported seed audio metadata.')
    duration = video.get('duration')
    require(type(duration) is int and duration > 0, 'Unsupported seed duration.')
    require(segment.get('source_timerange') == {'start': 0, 'duration': duration}
            and segment.get('target_timerange') == {'start': 0, 'duration': duration},
            'Seed must contain the complete untrimmed clip at timeline zero.')
    seen = set()
    for ref in segment['extra_material_refs']:
        require(ref in materials, 'Missing seed auxiliary material.')
        category, material = materials[ref]
        require(category in neutral['auxiliary'] and category not in seen, 'Unsupported or repeated seed auxiliary category.')
        expected = neutral['auxiliary'][category]
        if category == 'sound_channel_mappings':
            # CapCut 8.3 saves the neutral channel type as either "" or "none".
            # Accept only these observed spellings; every other field stays exact.
            require(material.get('type') in ('', 'none')
                    and type(material.get('audio_channel_mapping')) is int
                    and type(material.get('is_config_open')) is bool,
                    'Nonneutral or unsupported sound_channel_mappings auxiliary; create a fresh neutral UI seed.')
            expected = dict(expected, type=material['type'])
        matches(material, expected, {'id'}, f'{category} auxiliary')
        seen.add(category)
    require(seen == set(neutral['auxiliary']), 'Seed auxiliary defaults differ from the supported UI seed.')

def timeline_path(project, ident):
    require(isinstance(ident, str) and ident and Path(ident).name == ident and ident not in ('.', '..'),
            'Invalid timeline ID.')
    path = project / 'Timelines' / ident / 'draft_info.json'
    require(path.resolve().is_relative_to(project), 'Timeline escapes project.')
    return path

def verify_frame_clock(media, frames, fps, ffprobe=None):
    executable = shutil.which(str(ffprobe or 'ffprobe'))
    require(executable is not None, 'ffprobe required to verify millisecond-floor imported duration.')
    try:
        result = subprocess.run([executable, '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=codec_type,nb_frames,avg_frame_rate,r_frame_rate,duration_ts,time_base',
                                 '-of', 'json', str(media)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f'Cannot verify imported frame clock: {media}') from error
    require(result.returncode == 0, f'ffprobe failed to verify imported frame clock: {media}')
    try:
        streams = json.loads(result.stdout)['streams']
        require(len(streams) == 1, 'Expected one primary video stream.')
        stream = streams[0]
        require(stream['codec_type'] == 'video' and int(stream['nb_frames']) == frames
                and Fraction(stream['avg_frame_rate']) == fps and Fraction(stream['r_frame_rate']) == fps
                and int(stream['duration_ts']) * Fraction(stream['time_base']) == Fraction(frames, 1) / fps,
                f'Imported media frame clock differs from declared frames/FPS: {media}')
    except (KeyError, TypeError, ZeroDivisionError, json.JSONDecodeError) as error:
        raise ValueError(f'Unsupported imported media frame clock: {media}') from error

def build(project, kit, template, fps=Fraction(30), width=1080, height=1920,
          project_name='Editable montage', timeline_name='Editable montage timeline', apply=False, ffprobe=None):
    closed()
    project, kit, template = (Path(p).resolve() for p in (project, kit, template))
    require(project.is_dir() and kit.is_dir() and template.is_dir(), 'Missing project, kit, or template directory.')
    require(project != template and not template.is_relative_to(project), 'Use a separate copied template snapshot.')
    require(fps > 0 and width > 0 and height > 0, 'FPS and canvas dimensions must be positive.')
    seed_index = read(template / 'Timelines/project.json')
    candidates = []
    for item in seed_index['timelines']:
        d = read(timeline_path(template, item['id']))
        schema(d)
        segs = [s for t in d['tracks'] for s in t['segments']]
        if len(segs) == 1:
            candidates.append((item, d, segs[0]))
    require(len(candidates) == 1, 'Template must have exactly one saved single-clip timeline.')
    item, seed, segment = candidates[0]
    ident = item['id']
    require(len(seed['tracks']) == 1 and seed['tracks'][0].get('type') == 'video', 'Seed requires one video track.')
    neutral_seed(seed, segment, width, height)
    index = read(project / 'Timelines/project.json')
    require(sum(t['id'] == ident for t in index['timelines']) == 1, 'Target must retain the seed timeline ID.')
    require(index.get('main_timeline_id') == ident, 'Select the seeded timeline as active in CapCut first.')
    active_path = timeline_path(project, ident)
    draft = read(active_path)
    schema(draft)
    require(draft == seed, 'Target differs from the copied seed; preserve edits and use a fresh untouched UI seed/snapshot.')
    root = read(project / 'draft_info.json')
    schema(root)
    require(root == draft, 'Root and active timeline differ; save and close CapCut first.')
    require(len(draft['tracks']) == 1 and draft['tracks'][0].get('type') == 'video',
            'Selected timeline must contain only the seeded video track; preserve other timelines separately.')
    meta = read(project / 'draft_meta_info.json')
    imported = {}
    for group in meta['draft_materials']:
        for media in group['value']:
            if media.get('file_Path'):
                key = str(Path(media['file_Path']).resolve())
                require(key not in imported, 'Ambiguous duplicate imported media paths.')
                imported[key] = media
    manifest = read(kit / 'timeline.json')
    rows = manifest['cuts']
    require(isinstance(rows, list) and rows, 'No cuts.')
    total = 0
    inputs = []
    for row in rows:
        frames = row['frames']
        require(type(frames) is int and frames > 0, 'Cut frames must be positive integers.')
        require('fps' not in row or Fraction(str(row['fps'])) == fps, 'Cut FPS differs from requested FPS.')
        media = (kit / row['file']).resolve()
        require(not Path(row['file']).is_absolute() and media.is_relative_to(kit), 'Media must be inside the kit.')
        require(media.is_file(), f'Missing media: {media}')
        require(str(media) in imported, f'Import this clip into the selected project first: {media}')
        source = imported[str(media)]
        exact_duration = Fraction(frames * 1000000, 1) / fps
        duration = round(exact_duration)
        imported_duration = source.get('duration')
        require(type(imported_duration) is int, f'Unsupported imported duration: {media}')
        if imported_duration != duration:
            # Observed CapCut 8.3 import metadata can truncate to whole milliseconds.
            # This spelling needs independent verification of the actual file clock.
            require(imported_duration == (exact_duration // 1000) * 1000,
                    f'Imported duration differs from frames: {media}')
            verify_frame_clock(media, frames, fps, ffprobe)
        require(isinstance(source.get('id'), str) and source['id'], 'Missing imported media ID.')
        inputs.append((row, media, source, total, duration))
        total += frames
    require('frames' not in manifest or manifest['frames'] == total, 'Manifest total frame count differs.')
    original = {m['id']: (k, m) for k, vals in seed['materials'].items() for m in vals}
    require(segment['material_id'] in original and original[segment['material_id']][0] == 'videos', 'Missing seed video material.')
    require(all(r in original for r in segment['extra_material_refs']), 'Missing seed auxiliary material.')
    video_seed = original[segment['material_id']][1]
    # Preserve unrelated materials and project metadata; newly cloned IDs never share per-cut auxiliaries.
    materials = copy.deepcopy(draft['materials'])
    track = copy.deepcopy(draft['tracks'][0])
    track['segments'] = []
    for row, media, imported_media, start_frame, material_duration in inputs:
        start = round(Fraction(start_frame * 1000000, 1) / fps)
        end = round(Fraction((start_frame + row['frames']) * 1000000, 1) / fps)
        duration = end - start
        require(abs(duration - material_duration) <= 1, 'Frame boundary exceeds exact material duration tolerance.')
        v = copy.deepcopy(video_seed)
        v.update(id=uid(), duration=material_duration, path=str(media), material_name=media.name,
                 local_material_id=imported_media['id'])
        materials.setdefault('videos', []).append(v)
        s = copy.deepcopy(segment)
        s.update(id=uid(), material_id=v['id'], source_timerange={'start': 0, 'duration': duration},
                 target_timerange={'start': start, 'duration': duration}, extra_material_refs=[])
        for ref in segment['extra_material_refs']:
            category, aux_seed = original[ref]
            aux = copy.deepcopy(aux_seed)
            aux['id'] = uid()
            materials.setdefault(category, []).append(aux)
            s['extra_material_refs'].append(aux['id'])
        track['segments'].append(s)
    ids = [m['id'] for vals in materials.values() for m in vals]
    require(len(ids) == len(set(ids)), 'Duplicate material IDs.')
    idset = set(ids)
    require(all(s['material_id'] in idset and all(ref in idset for ref in s['extra_material_refs'])
                for s in track['segments']), 'Broken generated material graph.')
    duration = round(Fraction(total * 1000000, 1) / fps)
    draft.update(tracks=[track], materials=materials, duration=duration, fps=float(fps), name=timeline_name,
                 update_time=int(time.time() * 1000000))
    ratio = Fraction(width, height)
    draft['canvas_config'].update(width=width, height=height, ratio=f'{ratio.numerator}:{ratio.denominator}')
    index['update_time'] = draft['update_time']
    for t in index['timelines']:
        if t['id'] == ident:
            t.update(name=timeline_name, update_time=draft['update_time'])
    meta.update(draft_name=project_name, tm_duration=duration, tm_draft_modified=draft['update_time'],
                draft_need_rename_folder=False)
    meta['draft_timeline_materials_size_'] = sum(p.stat().st_size for _, p, _, _, _ in inputs)
    targets = [(project / 'draft_info.json', draft), (active_path, draft),
               (project / 'Timelines/project.json', index), (project / 'draft_meta_info.json', meta)]
    for path, _ in targets:
        require(path.resolve().is_relative_to(project) and not path.is_symlink(), 'Unsafe write destination.')
    report = dict(applied=False, cuts=len(rows), frames=total, duration_microseconds=duration,
                  fps=str(fps), canvas=f'{width}x{height}', gui_acceptance_pending=True)
    if not apply:
        return report
    closed()
    backup = Path(tempfile.mkdtemp(prefix=project.name + '-capcut-backup-', dir=project.parent))
    shutil.copytree(project, backup / 'project')
    originals = {p: p.read_bytes() for p, _ in targets}
    try:
        closed()
        for path, value in targets:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as tmp:
                json.dump(value, tmp, ensure_ascii=False, separators=(',', ':'))
                temp_path = Path(tmp.name)
            try:
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)
        require(all(read(p) == value for p, value in targets), 'Write verification failed.')
    except Exception:
        for path, raw in originals.items():
            path.write_bytes(raw)
        raise
    report.update(applied=True, backup=str(backup / 'project'))
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('project', 'kit', 'template-project'):
        p.add_argument('--' + option, type=Path, required=True)
    p.add_argument('--fps', type=Fraction, default=Fraction(30), help='Integer, decimal, or rational, e.g. 30000/1001')
    p.add_argument('--width', type=int, default=1080)
    p.add_argument('--height', type=int, default=1920)
    p.add_argument('--project-name', default='Editable montage')
    p.add_argument('--timeline-name', default='Editable montage timeline')
    p.add_argument('--ffprobe', help='Executable to verify millisecond-floor import clocks; defaults to PATH ffprobe')
    p.add_argument('--apply', action='store_true', help='Back up and update the selected project after preflight')
    a = p.parse_args()
    try:
        print(json.dumps(build(a.project, a.kit, a.template_project, a.fps, a.width, a.height,
                               a.project_name, a.timeline_name, a.apply, ffprobe=a.ffprobe), indent=2))
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        p.exit(1, f'Preflight/update failed: {error}\n')

if __name__ == '__main__':
    main()
