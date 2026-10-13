# Optional editable handoff

Reuse the approved cuts, source windows, order, exclusions, framing and sound. Preserve originals and prior exports. A flattened MP4 alone cannot recover source cuts or handles. Review any newly added source motion before extending an editing assembly.

## Portable clip kit

Export one numbered, precisely trimmed SDR BT.709 clip per cut, matching canvas/FPS and agreed sound. Include the reference MP4, `clips/`, relative-path `timeline.json`, source in/out points and short import instructions. Verify frame counts, color, decoding and actual playback. Copy compatible picture packets without reencoding; do not tone-map corrected SDR again.

Separate clips support rearranging, deleting, shortening and effects. Extending requires original sources or explicitly supplied handles. Audio adjustments already baked into clips cannot be undone with editor sliders. Keep further music, filters and finishing adjustable. The kit must be imported and arranged. Call it a native project only after checking it in the editor.

### Native-source kit helper

`render_native_kit.py` supports only 1080×1440/30fps from a hash-pinned `reframe_mixed` baseline. It requires exactly the baseline's unique IDs/order, verified native sources, capture anchors, reviewed framing and hash-pinned exclusions. Use another supported export route for other canvases/rates.

The version-1 plan declares `fps: 30`, `width: 1080`, `height: 1440`, `expected_cuts`, `expected_frames`, absolute `baseline_verification`/`excluded_ids` paths and both SHA-256 fields. `cuts` contains `asset_id`, `type` (`live_photo`, `native_video` or `still`), absolute `path`, `source_sha256`, integer `frames` (1–45), `active_rect`, `crop_rect`, `reason` and `framing_reason`. Keep the baseline source records and any intended `audio_gain_db`. Motion needs `start`; Live Photos retain baseline `anchor_seconds`. Rectangles match the baseline, and crops must be 3:4 inside active content. A native-video baseline must retain `original_source_identity`.

Run from the skill directory:

```sh
python3 scripts/render_native_kit.py --plan /absolute/reviewed-plan.json --work-dir /absolute/fresh-work --kit-dir /absolute/fresh-kit --ffmpeg /absolute/capable-ffmpeg --ffprobe /absolute/ffprobe --workers 2
```

The command checks the plan without rendering. Add `--execute` to render to new destinations outside Git. It checks source/anchor bounds, rejects trailing freezes, applies supported color conversion and recorded gains, and verifies exact video and audio timing and relative timeline paths. Watch and listen to the output after checks pass.

## Build a CapCut project

The builder supports the checked macOS CapCut desktop 8.3 schema (`version: 360000`, `new_version: "163.0.0"`). Other versions and direct photo import have not been verified. Prepared video clips support still, Live Photo and video selections. Use Computer Use to create the seed and check the finished project. Read the current UI before acting; do not reuse old coordinates or accessibility indexes.

1. In the project for this handoff, import all cuts from their final stable location. Make a saved timeline with exactly one complete, untrimmed kit video clip at timeline zero and neutral finishing. Select it as active, save and close CapCut.
2. Copy the complete project to a separate seed snapshot. The target project's root and active drafts must match each other and the untouched seed. Preserve changed projects; create a new untouched seed if needed. Do not substitute community draft JSON or edit global Home/project indexes. Resolve the project path again after a UI rename.
3. Run preflight with CapCut closed:

```sh
python3 scripts/build_capcut_project.py --project /absolute/selected-project --kit /absolute/clip-kit --template-project /absolute/copied-seed --fps 30 --width 1080 --height 1440 --ffprobe /absolute/ffprobe
```

`timeline.json` needs a nonempty ordered `cuts` array, e.g. `{"cuts": [{"file": "clips/01.mp4", "frames": 24, "fps": 30}]}`. Per-cut `fps` and top-level total `frames` are optional consistency checks. Pass rational project rates as `30000/1001` when applicable. Canvas flags must match the seed and kit.

4. Add `--apply` to build the requested project. It rechecks the process, schema, imported media/clock identity, materials, exact seed equality and neutral settings against [capcut-neutral-seed.json](capcut-neutral-seed.json). Effects, transforms, speed changes, keyframes, unknown settings and incompatible structures are rejected. Failed preflight leaves project bytes unchanged. Applying changes creates a full-project backup beside the project; keep it until the project passes the editor checks below. Restore the backup after a crash or rejected project rather than bypassing guards.
5. Open the project in CapCut. Check independent cut count/order, total duration, canvas/FPS, loaded media, crop/color, sound and playback across boundaries. Test requested shortening, deletion and rearrangement, undo test changes, and restore intended cuts. Check the track after Cut/Paste: it can create an overlay track. Save, close, reopen and verify the final project again.

The builder uses cumulative integer frames and exact rational clocks; its validation handles only verified rounding aliases, not arbitrary duration tolerances. Editor saves can floor a rational duration by one microsecond; accept that only with the actual media frame clock verified.

If the schema, seed or editor acceptance fails, restore the backup and import/arrange the kit through the UI. Report whether the project passed the editor checks as well as the helper checks. Moving the project and automatically relinking its media have not been verified; keep its referenced media available and preserve backups.
