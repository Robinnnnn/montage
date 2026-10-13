#!/usr/bin/env python3
"""Prepare private, reversible photo triage assets; never selects or deletes media.

Requires Pillow, pillow-heif and exiftool. All outputs belong outside Git.
Usage: python prepare_photos.py --archive SOURCE.zip --output PRIVATE_FOLDER
Self-checks: python prepare_photos.py --self-test
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import zipfile

from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps
from pillow_heif import register_heif_opener

# Pillow's HEIF plugin always decodes multichannel input to 8-bit.
register_heif_opener()
STILLS = {'.heic', '.heif', '.png', '.jpeg', '.jpg', '.webp'}
MOVIES = {'.mp4', '.mov'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_member(info):
    p = PurePosixPath(info.filename)
    if p.is_absolute() or '..' in p.parts or '\\' in info.filename or not p.parts:
        raise ValueError(f'Unsafe archive member: {info.filename}')
    if stat.S_ISLNK(info.external_attr >> 16):
        raise ValueError('Archive symlinks are forbidden')
    return p


def extract(archive, output):
    identity = sha256(archive)
    inputs = output / 'inputs'
    marker = output / 'extraction.json'
    if inputs.exists():
        if not marker.exists():
            raise ValueError('Existing inputs lack verified extraction identity')
        saved = json.loads(marker.read_text())
        if saved['archive_sha256'] != identity:
            raise ValueError('Existing extraction belongs to a different archive')
        for item in saved['files']:
            path = inputs / item['relative_path']
            if not path.is_file() or sha256(path) != item['sha256']:
                raise ValueError(f'Existing extraction changed: {path}')
        return inputs, saved
    staging = output / 'inputs.extracting'
    if staging.exists():
        raise ValueError('Partial extraction exists; inspect it before retrying')
    staging.mkdir()
    files = []
    with zipfile.ZipFile(archive) as z:
        seen = set()
        for info in z.infolist():
            relative = safe_member(info)
            if str(relative).casefold() in seen:
                raise ValueError('Duplicate or case-colliding ZIP paths')
            seen.add(str(relative).casefold())
            destination = staging / str(relative)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            # Reading each complete entry verifies its payload CRC in ZipFile.
            with z.open(info) as source, destination.open('xb') as target:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    target.write(block)
                    h.update(block)
            files.append({'relative_path': str(relative), 'size': info.file_size,
                          'zip_crc32': f'{info.CRC:08x}', 'sha256': h.hexdigest()})
    staging.rename(inputs)
    saved = {'archive_path': str(archive), 'archive_sha256': identity,
             'payload_crc_verified': True, 'files': files}
    marker.write_text(json.dumps(saved, indent=2))
    print(f'EXTRACTED {len(files)} files; all ZIP payload CRCs verified', flush=True)
    return inputs, saved


def metadata(inputs):
    raw = subprocess.check_output(['exiftool', '-json', '-G1', '-n', '-r', str(inputs)])
    records = json.loads(raw)
    return {str(Path(r['SourceFile']).resolve()): r for r in records}


def get_tag(record, names):
    for name in names:
        for key, value in record.items():
            if key.split(':')[-1] == name and value not in (None, ''):
                return value
    return None


def preview(source, destination, render_destination=None):
    with Image.open(source) as opened:
        original_size = list(opened.size)
        orientation = opened.getexif().get(274, 1)
        icc = opened.info.get('icc_profile')
        image = ImageOps.exif_transpose(opened)
        oriented_size = list(image.size)
        image = image.convert('RGB')
        srgb = ImageCms.createProfile('sRGB')
        if icc:
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                             srgb, outputMode='RGB')
            color = 'embedded ICC converted to sRGB'
        else:
            color = 'no embedded ICC; assumed sRGB'
        profile = ImageCms.ImageCmsProfile(srgb).tobytes()
        if render_destination:
            image.save(render_destination, 'JPEG', quality=95, icc_profile=profile)
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        image.save(destination, 'JPEG', quality=90, icc_profile=profile)
        small = image.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
        bits = [pixels[y * 9 + x] > pixels[y * 9 + x + 1] for y in range(8) for x in range(8)]
        dhash = sum(int(bit) << i for i, bit in enumerate(bits))
        # A second guard keeps identical structural hashes with different color apart.
        mean = tuple(image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0)))
        return {'dimensions': oriented_size, 'decoded_dimensions_before_exif': original_size,
                'decoded_exif_orientation': orientation, 'preview_dimensions': list(image.size),
                'color_conversion': color, 'preview_color_space': 'sRGB',
                'preview_bit_depth': 8, 'dhash': f'{dhash:016x}', 'mean_rgb': list(mean)}


def sheet(assets, destination):
    if len(assets) > 12:
        raise ValueError('Contact sheets support at most 12 images')
    canvas = Image.new('RGB', (4 * 320, 3 * 282 + 38), '#17191d')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 18)
    except OSError:
        font = ImageFont.load_default(size=18)
    draw.text((12, 8), 'PRIVATE SOURCE TRIAGE — unfiltered; do not deliver', font=font, fill='white')
    for i, asset in enumerate(assets):
        x, y = (i % 4) * 320, (i // 4) * 282 + 38
        with Image.open(asset['preview_path']) as im:
            im.thumbnail((304, 240), Image.Resampling.LANCZOS)
            canvas.paste(im, (x + (320 - im.width) // 2, y + (240 - im.height) // 2))
        label = asset['asset_id'] + '  ' + asset['filename']
        while draw.textlength(label, font=font) > 304:
            label = label[:-2] + '…'
        draw.text((x + 8, y + 247), label, font=font, fill='white')
    canvas.save(destination, quality=90)


def proposals(assets):
    exact = {}
    for asset in assets:
        exact.setdefault(asset['sha256'], []).append(asset['asset_id'])
    exact_groups = [v for v in exact.values() if len(v) > 1]
    # Pair proposals only, with no transitive closure or automatic representative.
    pairs = []
    for i, a in enumerate(assets):
        for b in assets[i + 1:]:
            if a['sha256'] == b['sha256']:
                continue
            distance = bin(int(a['dhash'], 16) ^ int(b['dhash'], 16)).count('1')
            color_distance = max(abs(x - y) for x, y in zip(a['mean_rgb'], b['mean_rgb']))
            ratio_a = a['dimensions'][0] / a['dimensions'][1]
            ratio_b = b['dimensions'][0] / b['dimensions'][1]
            if distance <= 2 and color_distance <= 8 and abs(ratio_a - ratio_b) < .02:
                pairs.append({'asset_ids': [a['asset_id'], b['asset_id']],
                              'dhash_distance': distance, 'max_mean_rgb_distance': color_distance,
                              'status': 'proposal_requires_visual_review'})
    return exact_groups, pairs


def run(archive, output):
    archive, output = archive.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs, extraction = extract(archive, output)
    meta = metadata(inputs)
    (output / 'metadata-private.json').write_text(json.dumps(meta, indent=2))
    stills = sorted(p for p in inputs.rglob('*') if p.is_file() and p.suffix.lower() in STILLS)
    movies = sorted(p for p in inputs.rglob('*') if p.is_file() and p.suffix.lower() in MOVIES)
    previews = output / 'previews'
    renders = output / 'render-stills'
    sheets = output / 'contact-sheets-private-unfiltered'
    for folder in (previews, renders, sheets):
        if folder.exists():
            raise ValueError(f'Output already exists; refusing to clobber: {folder}')
        folder.mkdir()
    def capture(p):
        return get_tag(meta.get(str(p), {}), ['DateTimeOriginal', 'CreationDate', 'CreateDate'])
    stills.sort(key=lambda p: (str(capture(p) or '9999'), p.name.casefold(), str(p)))
    movie_ids = {}
    for movie in movies:
        identifier = get_tag(meta.get(str(movie), {}), ['ContentIdentifier'])
        if identifier:
            movie_ids.setdefault(str(identifier), []).append(movie)
    hashes = {str(inputs / f['relative_path']): f['sha256'] for f in extraction['files']}
    assets = []
    for index, p in enumerate(stills, 1):
        asset_id = f'P{index:04d}'
        record = meta.get(str(p), {})
        identifier = get_tag(record, ['ContentIdentifier'])
        paired = movie_ids.get(str(identifier), []) if identifier else []
        filenames = [m for m in movies if m.parent == p.parent and m.stem.casefold() == p.stem.casefold()]
        candidates = paired or filenames
        a = {'asset_id': asset_id, 'still_path': str(p), 'filename': p.name,
             'sha256': hashes[str(p)], 'capture_datetime': capture(p),
             'preview_path': str(previews / f'{asset_id}.jpg'),
             'render_still_path': str(renders / f'{asset_id}.jpg'),
             'gps': {k: v for k, v in record.items() if 'GPS' in k},
             'provenance': {k: v for k, v in record.items() if k.split(':')[-1] in
                            {'Make', 'Model', 'Software', 'Artist', 'Copyright', 'OffsetTimeOriginal'}},
             'content_identifier': identifier,
             'source_exif_orientation': get_tag(record, ['Orientation']),
             'source_storage_dimensions': [get_tag(record, ['ImageWidth']), get_tag(record, ['ImageHeight'])],
             'motion_path': str(candidates[0]) if len(candidates) == 1 else None,
             'motion_candidates': [str(m) for m in candidates],
             'pair_evidence': 'embedded_content_identifier' if paired else
                              ('filename_only_unverified' if filenames else 'none'),
             'pair_verified': bool(len(paired) == 1),
             'anchor_timing_verified': False}
        a.update(preview(p, Path(a['preview_path']), Path(a['render_still_path'])))
        assets.append(a)
        if index % 12 == 0 or index == len(stills):
            page = (index - 1) // 12 + 1
            sheet(assets[(page - 1) * 12:index], sheets / f'page-{page:03d}.jpg')
            (output / 'manifest.partial.json').write_text(json.dumps(
                {'status': 'incomplete_private_preparation', 'assets': assets}, indent=2))
            print(f'SHEET {page:03d} ready ({index}/{len(stills)} previews)', flush=True)
    exact, near = proposals(assets)
    manifest = {'schema_version': 1, 'archive': {k: v for k, v in extraction.items() if k != 'files'},
                'privacy': 'Private unfiltered preparation only; excluded content not yet triaged',
                'counts': {'stills': len(stills), 'motion_candidates': len(movies), 'contact_sheets': (len(stills) + 11) // 12},
                'ordering': 'capture datetime if present, then casefolded filename and path; missing timestamps last',
                'preview_policy': 'EXIF orientation corrected; embedded ICC to sRGB; HEIF HDR decoded to 8-bit SDR by pillow-heif; missing ICC assumed sRGB',
                'assets': assets, 'exact_duplicate_groups': exact,
                'near_duplicate_proposals': near,
                'similarity_policy': 'dHash <=2 bits, max mean RGB difference <=8, aspect-ratio difference <0.02; pairs only, uncalibrated proposals require visual review',
                'motion_inventory': [{'path': str(m), 'sha256': hashes[str(m)],
                                      'content_identifier': get_tag(meta.get(str(m), {}), ['ContentIdentifier'])} for m in movies]}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'counts': manifest['counts'], 'exact_groups': len(exact), 'near_pairs': len(near)}), flush=True)


def self_test():
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        archive = root / 'test.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('folder/original.txt', b'preserved')
        out = root / 'out'
        out.mkdir()
        inputs, saved = extract(archive, out)
        assert saved['payload_crc_verified'] and (inputs / 'folder/original.txt').read_bytes() == b'preserved'
        extract(archive, out)
        (inputs / 'folder/original.txt').write_bytes(b'changed')
        try:
            extract(archive, out)
            raise AssertionError('Changed input accepted')
        except ValueError:
            pass
        for name in ['../escape', '/absolute', 'a\\b']:
            try:
                safe_member(zipfile.ZipInfo(name))
                raise AssertionError('Unsafe member accepted')
            except ValueError:
                pass
        source = root / 'oriented.jpg'
        im = Image.new('RGB', (80, 40), 'red')
        exif = im.getexif()
        exif[274] = 6
        im.save(source, exif=exif)
        result = preview(source, root / 'preview.jpg', root / 'render.jpg')
        assert result['dimensions'] == [40, 80]
        with Image.open(root / 'preview.jpg') as decoded:
            assert decoded.size == (40, 80) and decoded.mode == 'RGB'
            assert decoded.getexif().get(274, 1) == 1 and decoded.info['icc_profile']
        with Image.open(root / 'render.jpg') as decoded:
            assert decoded.size == (40, 80) and decoded.info['icc_profile']
        # Exercise embedded-profile conversion, rather than merely tagging output.
        profiled = root / 'profiled.png'
        im.save(profiled, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        result = preview(profiled, root / 'profiled.jpg')
        assert result['color_conversion'] == 'embedded ICC converted to sRGB'
        with Image.open(root / 'profiled.jpg') as decoded:
            assert decoded.getpixel((20, 20))[0] >= 250
        corrupted = root / 'corrupt.zip'
        with zipfile.ZipFile(corrupted, 'w') as z:
            z.writestr('data.bin', b'known payload', compress_type=zipfile.ZIP_STORED)
        data = corrupted.read_bytes()
        corrupted.write_bytes(data.replace(b'known payload', b'wrong payload', 1))
        corrupt_out = root / 'corrupt-out'
        corrupt_out.mkdir()
        try:
            extract(corrupted, corrupt_out)
            raise AssertionError('Corrupt payload accepted')
        except zipfile.BadZipFile:
            pass
        assets = [dict(asset_id=f'P{i:04d}', sha256=str(i), dhash='0' * 16,
                       mean_rgb=[100, 100, 100], dimensions=[80, 40]) for i in range(3)]
        assert len(proposals(assets)[1]) == 3
        assets[2]['mean_rgb'] = [200, 100, 100]
        assert len(proposals(assets)[1]) == 1
        # Real still decoding plus run-level discovery and filename pairing. Movie
        # payloads are inventory fixtures; metadata reading is intentionally mocked.
        formats_archive = root / 'formats.zip'
        webp = io.BytesIO()
        im.save(webp, format='WEBP')
        png = io.BytesIO()
        im.save(png, format='PNG')
        with zipfile.ZipFile(formats_archive, 'w') as z:
            z.writestr('photos/moment.WEBP', webp.getvalue())
            z.writestr('photos/MOMENT.MOV', b'movie inventory fixture')
            z.writestr('photos/ambiguous.png', png.getvalue())
            z.writestr('photos/ambiguous.mov', b'mov inventory fixture')
            z.writestr('photos/ambiguous.mp4', b'mp4 inventory fixture')
            z.writestr('elsewhere/moment.mov', b'different folder fixture')
            z.writestr('photos/ignored.gif', b'unsupported fixture')
            z.writestr('directory.webp/', b'')
            z.writestr('directory.mov/', b'')
        formats_out = root / 'formats-out'
        with patch(__name__ + '.metadata', return_value={}):
            run(formats_archive, formats_out)
        manifest = json.loads((formats_out / 'manifest.json').read_text())
        assert manifest['counts'] == {'stills': 2, 'motion_candidates': 4, 'contact_sheets': 1}
        by_name = {a['filename']: a for a in manifest['assets']}
        moment = by_name['moment.WEBP']
        assert Path(moment['motion_path']).name == 'MOMENT.MOV'
        assert len(moment['motion_candidates']) == 1
        ambiguous = by_name['ambiguous.png']
        assert ambiguous['motion_path'] is None and len(ambiguous['motion_candidates']) == 2
        for asset in manifest['assets']:
            assert asset['pair_evidence'] == 'filename_only_unverified'
            assert not asset['pair_verified'] and not asset['anchor_timing_verified']
            assert Path(asset['render_still_path']).is_file()
        assert len(manifest['motion_inventory']) == 4
    print('SELF TEST PASS: safe extraction, CRC rejection, identity reuse, tamper rejection, orientation, full-resolution render, ICC conversion, sRGB JPEG, conservative pair guards, WebP/MOV discovery and unverified filename pairing')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.archive and args.output:
        run(args.archive, args.output)
    else:
        parser.error('--archive and --output are required unless --self-test is used')
