---
name: dj-set-ripper
description: Extract a tracklist from a DJ set or mix link and source the individual songs with dj-mp3-sourcer. Use for YouTube, SoundCloud, Mixcloud, 1001Tracklists, or a pasted tracklist; produce a per-track result log.
---

# DJ set ripper

Extract the set's tracklist, source its individual tracks, and preserve the result for every entry. Install the sibling [dj-mp3-sourcer](../dj-mp3-sourcer/SKILL.md) skill for individual-track sourcing; do not substitute one download of the full mix for the requested separate tracks.

## Extract the tracklist

Use available page-fetch/search tools for the supplied URL's description and track metadata. For YouTube, `yt-dlp --dump-single-json "<url>"` can expose its description. Read the relevant description or structured tracklist, preserving its source URL. 1001Tracklists can be useful when the set page has no tracklist.

Parse a JSON array with `number`, `timestamp`, `artist`, and `title`. Preserve remix/mix names and meaningful artist spelling. Use `null` for missing timestamps. Keep unidentified `ID` entries and record uncertainty; skip timestamp-only lines. Never fill in unidentified music by guessing. If no tracks can be extracted, explain the result and request a pasted tracklist if needed.

Save this tracklist with the set's title and source URL in a dedicated output folder outside the skill repository. Derive a safe folder name or use the user's destination; metadata is text, not a shell command or path.

## Source individual tracks

Use the [dj-mp3-sourcer workflow](../dj-mp3-sourcer/SKILL.md) for every identified track. Deduplicate identical artist/title/version requests while retaining all original tracklist positions. Leave unidentified tracks in the log. Respect the user's free-only preference and exact remix identity; surface purchase links instead of buying tracks.

When workers are available, distribute distinct tracks in bounded batches of three to five. Collect their filenames, source URLs, measured bitrate/size, and status. Wait for all batches before normalizing filenames so workers do not rename each other's files.

Use the bundled Python 3 helper to preview filenames against the verified `artist`/`title` tracklist:

```sh
python3 scripts/normalize_filenames.py /absolute/set-folder /absolute/tracklist.json
```

Inspect the plan, then repeat with `--apply`. It skips full mixes, occupied targets, ambiguous matches, and symlinks. Retain unmatched files for review. The shell entrypoint `scripts/normalize-filenames.sh` accepts the same arguments.

## Optional full mix

Download the full mix only when the user requests it. Use a distinct name such as `Set Name [Full Mix].mp3`, and record its source and result separately. `yt-dlp`, FFmpeg, and ffprobe are needed for supported audio extraction; check their installed capabilities first.

## Result log

Write a timestamped log in the set folder with the original URL, extracted tracklist, and one result per entry. Include artist/title/version, source, status, filename or purchase link, and measured size/bitrate when a file exists. Distinguish downloaded, purchase available, not found, alternate version, and unidentified results. Explain meaningful failures such as an unavailable remix or region restriction. Summarize the totals without counting duplicate positions as extra downloads.

Keep downloaded audio, logs, and user tracklists outside this skill repository. Deliver links to actual files and the log, with unresolved entries visible.
