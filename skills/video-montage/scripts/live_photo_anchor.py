#!/usr/bin/env python3
"""Read a local Live Photo's pair identifier and timed anchor on macOS.

No Photos-library access or media mutation. Requires Swift and ffprobe. The
Apple MakerNote key 17 convention is verified on representative exports, not
an assertion that every image format/export preserves it. Missing/conflicting
metadata never becomes a midpoint. Output may contain private identifiers;
keep result JSON in the private run folder, outside Git.
"""
from __future__ import annotations
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SWIFT_SOURCE = r'''
import Foundation
import AVFoundation
import ImageIO
func timing(_ t: CMTime) -> [String: Any] {
    return ["value": t.value, "timescale": t.timescale, "epoch": t.epoch,
            "valid": t.isValid && t.isNumeric]
}
var result: [String: Any] = [:]
do {
    let args = CommandLine.arguments
    if args.count > 2 && args[2] != "-" {
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any] else {
            throw NSError(domain: "LivePhotoAnchor", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Cannot read still image metadata"])
        }
        if let maker = props[kCGImagePropertyMakerAppleDictionary as String] as? [String: Any],
           let id = maker["17"] as? String {
            result["still_identifier"] = id
        }
    }
    let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
    let metadata = try await asset.load(.metadata)
    var ids: [String] = []
    for item in metadata where item.identifier?.rawValue == "mdta/com.apple.quicktime.content.identifier" {
        if let value = try await item.load(.stringValue) { ids.append(value) }
    }
    result["motion_identifiers"] = ids
    result["asset_duration"] = timing(try await asset.load(.duration))
    var anchors: [[String: Any]] = []
    var errors: [String] = []
    for track in try await asset.loadTracks(withMediaType: .metadata) {
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: nil)
        reader.add(output)
        let adaptor = AVAssetReaderOutputMetadataAdaptor(assetReaderTrackOutput: output)
        guard reader.startReading() else { throw reader.error ?? NSError(domain: "LivePhotoAnchor", code: 2) }
        while let group = adaptor.nextTimedMetadataGroup() {
            for item in group.items where item.identifier?.rawValue == "mdta/com.apple.quicktime.still-image-time" {
                // The item is a marker. Its payload (-1 on tested files) is NOT seconds.
                anchors.append(["track_id": track.trackID, "time": timing(group.timeRange.start),
                                "sample_duration": timing(group.timeRange.duration),
                                "identifier": item.identifier!.rawValue])
            }
        }
        if reader.status != .completed {
            errors.append(reader.error?.localizedDescription ?? "Metadata reader did not complete")
        }
    }
    result["timed_anchors"] = anchors
    result["reader_errors"] = errors
} catch {
    result["error"] = error.localizedDescription
}
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
'''


def run(command: list[str], timeout: int = 120) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {command[0]}")
    return result.stdout


def read_metadata(motion: Path, still: Path | None) -> dict:
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        raise RuntimeError("Anchor metadata reading requires macOS with Swift installed")
    # Cache only generic compiled code; media and identifiers are never cached.
    digest = hashlib.sha256(SWIFT_SOURCE.encode()).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / "montage-live-photo-reader"
    cache.mkdir(mode=0o700, exist_ok=True)
    binary = cache / f"reader-{digest}"
    if not binary.exists():
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            source = Path(tmp) / "reader.swift"
            source.write_text(SWIFT_SOURCE)
            built = Path(tmp) / "reader"
            run(["swiftc", str(source), "-o", str(built)])
            built.replace(binary)
    return json.loads(run([str(binary), str(motion), str(still) if still else "-"]))


def as_fraction(timing: dict) -> Fraction | None:
    if not timing.get("valid") or timing.get("epoch") != 0 or timing.get("timescale", 0) <= 0:
        return None
    return Fraction(timing["value"], timing["timescale"])


def assess(metadata: dict, frame_pts: list[Fraction], last_duration: Fraction,
           candidate_stem: bool = False) -> dict:
    """Pure assessment for real readings and synthetic negative/zero tests."""
    report = dict(metadata)
    warnings = []
    motion_ids = set(metadata.get("motion_identifiers", []))
    still_id = metadata.get("still_identifier")
    if still_id and len(motion_ids) == 1:
        pairing = "embedded_identifier_match" if still_id in motion_ids else "embedded_identifier_mismatch"
    elif len(motion_ids) > 1:
        pairing = "conflicting_motion_identifiers"
    elif candidate_stem:
        pairing = "filename_candidate_only"
    else:
        pairing = "unverified"
    report["pairing"] = pairing
    anchors = metadata.get("timed_anchors", [])
    a = as_fraction(anchors[0].get("time", {})) if len(anchors) == 1 else None
    duration = as_fraction(metadata.get("asset_duration", {}))
    if metadata.get("error") or metadata.get("reader_errors"):
        state = "metadata_read_failed"
    elif not anchors:
        state = "missing_anchor"
    elif len(anchors) > 1:
        state = "multiple_anchors_require_review"
    elif a is None or duration is None or a < 0 or a >= duration:
        state = "invalid_anchor"
    elif not frame_pts or not (frame_pts[0] <= a < frame_pts[-1] + last_duration):
        state = "anchor_outside_decodable_video_bounds"
    else:
        state = "valid_timed_metadata"
        report["anchor"] = {"value": a.numerator, "timescale": a.denominator, "seconds": float(a),
                            "method": "timed_metadata_group_presentation_time",
                            "kind": "exported_still_marker"}
        nearest = min(frame_pts, key=lambda p: abs(p - a))
        report["nearest_video_frame"] = {"seconds": float(nearest), "offset_seconds": float(nearest - a)}
        warnings.append("Export metadata cannot establish whether the chosen still is the original shutter photo or a later edited key photo; visually confirm the still and anchor neighborhood.")
    report["anchor_status"] = state
    report["motion_eligible_for_review"] = state == "valid_timed_metadata" and pairing == "embedded_identifier_match"
    report["confidence"] = "strong_metadata_evidence" if report["motion_eligible_for_review"] else "unresolved"
    if pairing == "filename_candidate_only":
        warnings.append("Matching stems identify a candidate only; embedded pairing is unverified.")
    if state != "valid_timed_metadata":
        warnings.append("Keep the still unless reliable anchor evidence is obtained. No midpoint fallback was applied.")
    report["warnings"] = warnings
    return report


def source_identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"name": path.name, "size": path.stat().st_size, "sha256": digest.hexdigest()}


def inspect(motion: Path, still: Path | None, ffprobe: str = "ffprobe") -> dict:
    meta = read_metadata(motion, still)
    probe = json.loads(run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(motion)]))
    videos = [s for s in probe["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise RuntimeError("Motion resource contains no video stream")
    primary = max(videos, key=lambda s: s.get("width", 0) * s.get("height", 0))
    decoded = json.loads(run([ffprobe, "-v", "error", "-select_streams", str(primary["index"]), "-show_frames", "-show_entries", "frame=best_effort_timestamp,pkt_duration,duration", "-of", "json", str(motion)]))
    tb = Fraction(primary["time_base"])
    pts = sorted({int(f["best_effort_timestamp"]) * tb for f in decoded.get("frames", []) if "best_effort_timestamp" in f})
    durations = [int(f.get("duration", f.get("pkt_duration", 0))) * tb for f in decoded.get("frames", [])]
    last_duration = durations[-1] if durations else Fraction(0)
    report = assess(meta, pts, last_duration, bool(still and still.stem == motion.stem))
    report["sources"] = {"motion": source_identity(motion)}
    if still is not None:
        report["sources"]["still"] = source_identity(still)
    report["primary_video_stream"] = primary["index"]
    report["decoded_frame_count"] = len(pts)
    report["container_brand"] = probe.get("format", {}).get("tags", {}).get("major_brand")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--still", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    try:
        for path in [args.motion, args.still]:
            if path is not None and not path.is_file():
                raise RuntimeError(f"Input is not a file: {path}")
        print(json.dumps(inspect(args.motion, args.still, args.ffprobe), indent=2, sort_keys=True))
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
