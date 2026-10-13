# Photos and Live Photos

## Prepare photos

Requirements: Python 3 with Pillow and pillow-heif, plus ExifTool. Reading Live Photo capture timing requires macOS, Swift and ffprobe. Rendering requires FFmpeg with zscale and tonemap, plus ffprobe. Run commands from the skill directory.

```sh
python3 scripts/prepare_photos.py --archive /absolute/source.zip --output /absolute/prepared-photos
```

The helper verifies archive identity and payload CRCs, rejects unsafe or colliding paths, and refuses to reuse an extraction whose contents changed. It lists HEIC/HEIF, PNG, JPEG/JPG, WebP and MOV/MP4; produces orientation-correct sRGB previews, full-resolution render JPEGs, contact sheets and `manifest.json`.

Embedded ICC profiles are converted to sRGB; images without a profile are assumed sRGB. HEIF becomes 8-bit SDR. Check representative colors and dimensions. Use full-resolution render JPEGs for the edit. Raw contact sheets remain private; filter delivered previews to selected, permitted assets.

Review similar shots together, keeping every original and its source record. Similarity groups are suggestions. Enlarge unclear images and check that the shortlist covers the story.

## Verify Live Photos

Treat the still and motion as one asset. Their embedded identifiers must match; similar filenames are not enough. Leave the pair unresolved if metadata is missing, conflicts or matches multiple files.

```sh
python3 scripts/live_photo_anchor.py --motion /absolute/photo.MOV --still /absolute/photo.HEIC --ffprobe /absolute/ffprobe > /absolute/anchor.json
```

The helper reads the timed `com.apple.quicktime.still-image-time` sample. Its presentation timestamp is the capture anchor; the marker payload is not seconds. Zero is a valid anchor. PhotoKit's `PHLivePhotoEditingContext.photoTime` can supply timing when available. The capture marker may differ from a key photo chosen later: compare the still with nearby motion frames. Do not invent a midpoint for missing timing.

Before using motion, verify the pair, intended anchor, decoded frames and primary-track bounds. The renderer maps the first video stream; resolve a different primary stream first. Select a clean window containing the anchor, inspect its actual frames for privacy, shake, blinks and the camera moving away, and check sound through playback. Use the selected still when pairing/timing is unresolved or motion harms the shot; record the reason. If the user asks to favor motion, inspect it before falling back to the still.

Inspect distinct decoded frames within the selected window. Short variable-frame-rate clips may have fewer frames than the sample count requested; repeated frames do not show more motion. Trim source timestamps before frame-rate conversion. Never pull outside-window frames to fill duration. Primary-track duration governs the end boundary even when a final frame reports a longer duration. The renderer checks frame-rate conversion within those bounds, limits repeated end frames, and checks exact audio length.

## Render a mixed edit

`render_mixed.py` currently accepts only version 2, 1080×1920, 30fps edits. Use this minimal schema, replacing the example paths and hashes:

```json
{
  "version": 2, "fps": 30, "width": 1080, "height": 1920,
  "selections": [
    {"asset_id": "still-1", "type": "still", "path": "/absolute/render.jpg",
     "source_sha256": "<64 lowercase hex characters>", "frames": 24,
     "reason": "Establish the place"},
    {"asset_id": "live-1", "type": "live_photo", "path": "/absolute/photo.MOV",
     "source_sha256": "<64 lowercase hex characters>", "frames": 30,
     "start": 0.4, "anchor_seconds": 0.8, "anchor_method": "verified timed metadata",
     "reason": "Retain the captured gesture"}
  ]
}
```

Every selection needs a unique ID, existing absolute path, matching SHA-256, integer frame count and specific reason. Keep the still/motion pairing and original still source record in extra fields. `video_segment` uses an already finished, compatible 1080×1920 BT.709 H.264/PCM MKV with exactly the declared frames; it does not trim a longer segment.

Default duration is 24–60 frames; cuts over 30 require `extended: true` and a reason explaining the extra time. If the user requests faster pacing, set `min_frames` or `still_min_frames` in the edit manifest using values supported by script validation. Keep the default when no override was requested.

```sh
python3 scripts/render_mixed.py --edit /absolute/edit.json --work-dir /absolute/fresh-render --output /absolute/version.mp4 --ffmpeg /absolute/capable-ffmpeg
```

The helper refuses to overwrite files or write media inside Git. It converts prepared sRGB stills and supported tagged motion to BT.709, including its supported HLG treatment. Resolve unsupported HDR or incomplete wide-gamut metadata before rendering; retagging is not conversion. Images fit with padding. New motion audio receives edge fades; stills are silent. Finished segment audio is retained unless an explicit gain changes it.

`verification.json` reports exact frames and stream/timeline checks. Inspect export frames for crop, orientation and color, then play the export to check motion and sound.

## Reframe an accepted edit

`reframe_mixed.py` uses the prior renderer's verified H.264/PCM segments. It preserves reviewed windows and finished sound; it reencodes the picture and does not convert native HDR.

```sh
python3 scripts/reframe_mixed.py --plan /absolute/framing.json --work-dir /absolute/fresh-reframe --output /absolute/reframed.mp4 --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe
```

This is a read-only preflight; add `--execute` to render. A version-1 plan needs `fps: 30`, positive even `width`/`height` within the helper's H.264 limit, `baseline_verification` and its SHA-256, an absolute `excluded_ids` JSON file (list or `{"excluded_ids": [...]}`), `removed_ids`, and ordered `cuts`. Pin the exclusion hash with `excluded_ids_sha256` when possible.

Each cut retains baseline `asset_id`, `type`, `frames`, absolute `segment` and `segment_sha256`, and adds `active_rect`, `crop_rect` and `framing_reason`. Rectangles use even integer `x`, `y`, `width`, `height` in segment pixels. Find the active content using the source dimensions after rotation and how it was fitted; dark pixels alone cannot identify padding. Keep crops inside active content and inspect the first, middle and last selected frames. If stretching is requested, use the full active rectangle and state its distortion.

Every baseline ID must be either retained or in `removed_ids`, never both. Keep baseline order; only `opener_exception` may move one retained ID to the front, with a reason. Optional `expected_cuts`/`expected_frames` check totals. Inspect output frames after successful verification. For editable export, see [editable-handoff.md](editable-handoff.md).
