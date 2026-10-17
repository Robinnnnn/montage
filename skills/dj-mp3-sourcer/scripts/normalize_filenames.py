#!/usr/bin/env python3
"""Preview conservative MP3 renames from a verified artist/title tracklist."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import unicodedata


def words(value):
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return set(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def component(value):
    # Metadata is a label, never a path. Keep each result inside one directory.
    value = "".join("-" if c in '/\\:' or ord(c) < 32 or ord(c) == 127 else c for c in value)
    value = " ".join(value.split()).strip(" .")
    if not value or len(value.encode("utf-8")) > 220:
        raise ValueError("empty or excessively long filename component")
    return value


def plan(directory, entries):
    files = sorted(
        (p for p in directory.iterdir()
         if p.suffix.casefold() == ".mp3" and p.is_file() and not p.is_symlink()
         and not {"full", "mix"}.issubset(words(p.stem))),
        key=lambda p: p.name.casefold(),
    )
    occupied = {p.name.casefold() for p in directory.iterdir()}
    candidates, notes = [], []
    seen = set()
    for number, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("artist", "title")):
            raise ValueError("track %d needs string artist and title" % number)
        artist, title = entry["artist"].strip(), entry["title"].strip()
        if not artist or not title:
            raise ValueError("track %d has an empty artist or title" % number)
        if artist.casefold() == "id" or title.casefold() == "id":
            notes.append("track %d: unidentified; skipped" % number)
            continue
        target = component(artist) + " - " + component(title) + ".mp3"
        if len(target.encode("utf-8")) > 240:
            raise ValueError("track %d produces an excessively long filename" % number)
        if target.casefold() in seen:
            notes.append("track %d: duplicate target; skipped" % number)
            continue
        seen.add(target.casefold())
        if target.casefold() in occupied:
            notes.append("track %d: destination already exists; skipped" % number)
            continue
        required = words(artist) | words(title)
        if not required:
            notes.append("track %d: no usable matching words; skipped" % number)
            continue
        matches = [p for p in files if required.issubset(words(p.stem))]
        if len(matches) != 1:
            notes.append("track %d: %d matching files; skipped" % (number, len(matches)))
            continue
        candidates.append((matches[0], directory / target))
    uses = Counter(source for source, _ in candidates)
    result = []
    for source, target in candidates:
        if source.name.casefold() in seen:
            notes.append("%s: already names a track in this list; skipped" % source.name)
        elif uses[source] > 1:
            notes.append("%s: matches multiple tracks; skipped" % source.name)
        else:
            result.append((source, target))
    return result, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("tracklist", type=Path)
    parser.add_argument("--apply", action="store_true", help="apply the displayed plan; default is preview only")
    args = parser.parse_args()
    try:
        directory = args.directory.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("output directory is not a directory")
        entries = json.loads(args.tracklist.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("tracklist must be a JSON array")
        renames, notes = plan(directory, entries)
        for note in notes:
            print(note)
        completed = 0
        for source, target in renames:
            print("%s -> %s" % (source.name, target.name))
            if args.apply:
                # Exclusive creation avoids replacing a file created after planning.
                # Hard-linking within the same directory preserves the original bytes.
                if source.is_symlink() or not source.is_file():
                    raise ValueError("source changed after planning: %s" % source.name)
                os.link(source, target, follow_symlinks=False)
                source.unlink()
                completed += 1
        print("%s: %d rename(s)" % ("Applied" if args.apply else "Preview", completed if args.apply else len(renames)))
        return 0
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
