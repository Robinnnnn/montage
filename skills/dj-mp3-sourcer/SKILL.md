---
name: dj-mp3-sourcer
description: Find and download individual music tracks from supplied links or a tracklist, preferring the requested mix and returning purchase links when appropriate. Use for single tracks or batches; use dj-set-ripper to extract a DJ set's tracklist first.
---

# DJ MP3 sourcer

Identify the exact artist, title, and remix from the user's links or tracklist. Source that version, download audio the user can access, and report where each result came from. Prefer an extended mix when the user has not requested another version. Keep a requested remix's identity; a different original or radio edit is not an equivalent match.

## Tools and sources

Use the available web search/page tools for discovery. Downloads use `yt-dlp` or `spotdl`; audio extraction and inspection need FFmpeg and ffprobe. The optional filename helper needs Python 3. Inspect installed command help before relying on flags. Install missing tools only within the requested environment and scope.

Search Bandcamp, Beatport, Amazon's digital music store, Spotify metadata, then YouTube. Stop at a verified suitable match, taking the exact version into account. Surface purchase links and observed prices for paid releases; do not purchase automatically. In free-only mode, skip purchase searches and use available free or user-accessible sources. Unavailable services, missing releases, and region restrictions are results to report rather than reasons to substitute another mix silently.

Spotify supplies metadata to spotDL; it does not establish the downloaded audio's provenance or quality. An MP3 encoded at 320 kb/s cannot recover quality missing in its source. Report the measured output bitrate separately from the identified source.

## Download and verify

Use the user's destination, or a dedicated folder under `~/Downloads`. Preserve existing files and separate full mixes from individual tracks. For example, with placeholders replaced and arguments quoted:

```sh
spotdl download "<spotify-url>" --output "/absolute/output/{artist} - {title}.{output-ext}" --format mp3 --bitrate 320k
yt-dlp -x --audio-format mp3 --audio-quality 0 --embed-thumbnail --add-metadata -o "/absolute/output/%(title)s.%(ext)s" "<source-url>"
```

Verify artist/title/version, duration, decoding, and output metadata. Preserve available tags and cover art; include BPM/key only when sourced. Record the source URL and actual result, including a purchase link, unavailable result, or alternate version needing review.

For batches, use a bounded number of workers when supported. Give each worker distinct tracks/files and collect all results before renaming. Network limits and tool availability determine concurrency.

## Filename normalization

Keep the verified tracklist as JSON outside the skill repository:

```json
[{"artist": "Example Artist", "title": "Example Track (Extended Mix)"}]
```

Resolve the helper relative to this skill directory. It previews matching filenames without changing them:

```sh
python3 scripts/normalize_filenames.py /absolute/output /absolute/tracklist.json
```

Inspect the plan, then repeat with `--apply`. The helper uses literal normalized words, sanitizes filename components, skips symlinks and full mixes, and refuses ambiguous matches or occupied destinations. Unmatched files remain unchanged; verify them manually rather than forcing a rename. `scripts/normalize-filenames.sh` is a compatible shell entrypoint.

Report downloaded files with source, actual format/bitrate, and any unresolved identity or quality issue. Do not imply that a valid file proves a correct musical match.
