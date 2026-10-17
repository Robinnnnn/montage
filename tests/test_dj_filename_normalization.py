"""File-operation regression checks, without network calls or real audio."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("dj-mp3-sourcer", "dj-set-ripper")


class FilenameNormalizationTests(unittest.TestCase):
    def run_helper(self, skill, tracks, files, apply=True, symlink=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        output = root / "audio"
        output.mkdir()
        for name in files:
            (output / name).write_bytes(name.encode())
        if symlink:
            outside = root / "outside.mp3"
            outside.write_bytes(b"outside")
            (output / symlink).symlink_to(outside)
        tracklist = root / "tracks.json"
        tracklist.write_text(json.dumps(tracks))
        command = [sys.executable, str(ROOT / "skills" / skill / "scripts" / "normalize_filenames.py"), str(output), str(tracklist)]
        if apply:
            command.append("--apply")
        result = subprocess.run(command, capture_output=True, text=True)
        return result, output

    def test_preview_preserves_files_and_apply_processes_multiple_tracks(self):
        tracks = [{"artist": "Artist", "title": "One"}, {"artist": "Artist", "title": "Two"}]
        files = ["Artist One Official.mp3", "Artist Two Video.mp3"]
        for skill in SKILLS:
            with self.subTest(skill=skill):
                result, output = self.run_helper(skill, tracks, files, apply=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(sorted(p.name for p in output.iterdir()), sorted(files))
                result, output = self.run_helper(skill, tracks, files)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((output / "Artist - One.mp3").read_bytes(), files[0].encode())
                self.assertEqual((output / "Artist - Two.mp3").read_bytes(), files[1].encode())

    def test_metadata_cannot_escape_directory(self):
        for skill in SKILLS:
            with self.subTest(skill=skill):
                result, output = self.run_helper(skill, [{"artist": "../Artist", "title": "../Song"}], ["Artist Song.mp3"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(list(output.iterdir())), 1)
                self.assertEqual(next(output.iterdir()).read_bytes(), b"Artist Song.mp3")
                self.assertEqual(sorted(p.name for p in output.parent.iterdir()), ["audio", "tracks.json"])

    def test_ambiguous_files_existing_targets_and_symlinks_are_untouched(self):
        tracks = [{"artist": "Artist", "title": "Song"}]
        scenarios = [(["Artist Song A.mp3", "Artist Song B.mp3"], None),
                     (["Artist Song Video.mp3", "Artist - Song.mp3"], None),
                     ([], "Artist Song.mp3")]
        for skill in SKILLS:
            for files, symlink in scenarios:
                with self.subTest(skill=skill, files=files, symlink=symlink):
                    result, output = self.run_helper(skill, tracks, files, symlink=symlink)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(sorted(p.name for p in output.iterdir()), sorted(files + ([symlink] if symlink else [])))

    def test_shared_source_is_not_claimed_by_two_tracks(self):
        tracks = [{"artist": "Artist", "title": "Song"}, {"artist": "Artist", "title": "Song Remix"}]
        for skill in SKILLS:
            result, output = self.run_helper(skill, tracks, ["Artist Song Remix.mp3"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "Artist Song Remix.mp3").exists())

    def test_clean_specific_version_is_not_renamed_to_another_track(self):
        tracks = [{"artist": "Artist", "title": "Song Remix"}, {"artist": "Artist", "title": "Song"}]
        for skill in SKILLS:
            result, output = self.run_helper(skill, tracks, ["Artist - Song Remix.mp3"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "Artist - Song Remix.mp3").exists())

    def test_empty_tracklist_is_valid_and_malformed_entries_fail_before_renaming(self):
        for skill in SKILLS:
            result, output = self.run_helper(skill, [], ["Artist Song.mp3"])
            self.assertEqual(result.returncode, 0, result.stderr)
            tracks = [{"artist": "Artist", "title": "Song"}, {"artist": None, "title": "Invalid"}]
            result, output = self.run_helper(skill, tracks, ["Artist Song.mp3"])
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((output / "Artist Song.mp3").exists())


if __name__ == "__main__":
    unittest.main()
