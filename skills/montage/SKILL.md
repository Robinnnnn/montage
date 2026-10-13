---
name: montage
description: Create or revise montages from photos, Live Photos, and videos, such as travel recaps and family highlights. Optionally export separate clips for further editing in a video editor.
---

# Montage

The user describes the montage and points to the footage. Handle sorting and selection, then deliver an MP4 after checking the render and playback.

## Workflow

1. Locate the footage and apply any requested date range. Preserve originals and work in a separate folder outside this repository.
2. Catalog the files, create contact sheets and flag duplicates. Choose what belongs based on the request and the footage. Exclude files without deleting them.
3. Look through the full collection, then watch promising moments closely. Include a mix of people, details, action and scenery where it suits the montage. Check where each clip starts and ends; still frames cannot tell you how motion or sound plays.
4. Record each source file, clip start/end, photo duration and selection reason in the edit manifest. Plan order, pacing and framing to suit the request.
5. Validate and render. Check the output's crop and color, then watch and listen for problems with motion, pacing and sound. Revise as needed or from user feedback; keep previous exports.
6. Deliver the MP4 and keep the cut list for later revisions.

Keep footage and generated files outside Git. Omit excluded footage from previews and handoffs too. Upload or share media only when the user authorizes it.

## Video folders

Requires Python 3.9+, FFmpeg and ffprobe. Run commands from this skill directory; replace paths with the user's locations.

```sh
python3 scripts/montage.py prepare --input /absolute/videos --work-dir /absolute/new-run
```

Open the generated contact sheets. Edit `edit.json` using IDs from `manifest.json`; array order determines the montage order:

```json
{
  "selections": [
    {"clip_id": "c0001", "start": 4.25, "end": 5.15, "reason": "The visible gesture completes here"}
  ]
}
```

The video helper defaults to 0.8–2-second cuts. Adjust `--min-duration`, `--normal-max` and `--max-duration` during preparation to match requested pacing. Cuts above `normal_max` need `extended: true` and a reason for the extra time. Avoid padding with weak footage to reach a target length.

```sh
python3 scripts/montage.py validate --work-dir /absolute/new-run
python3 scripts/montage.py render --work-dir /absolute/new-run --output /absolute/montage.mp4
python3 scripts/montage.py review --input /absolute/montage.mp4 --work-dir /absolute/new-review
```

Rendering defaults to 1920×1080/30fps; use `--width 1080 --height 1920` for vertical. The renderer fits footage with padding rather than stretching it. Check any crops. Use `--audio mute` when source sound is unwanted. Keep added music and effects editable when an editor handoff is requested.

HLG conversion requires FFmpeg's `zscale` and `tonemap` filters. Set `MONTAGE_FFMPEG` to use another FFmpeg build when needed. Convert unsupported HDR before rendering; changing color tags alone does not convert the picture. Compare source and output colors on a few representative shots.

## Other media

- **Photos or Live Photos:** read [media.md](references/media.md) for preparation, pairing, timing and rendering. Keep a Live Photo's still and motion together.
- **GoPro or long recordings:** read [gopro.md](references/gopro.md) for split recordings, camera clocks, framing and color.

## Optional editable handoff

When requested, follow [editable-handoff.md](references/editable-handoff.md) to export separate numbered clips from the approved edit. Use Computer Use to assemble and check the project in the chosen editor. Otherwise, deliver the MP4.
