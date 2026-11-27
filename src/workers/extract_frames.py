"""Sample ordered RGB PNG frames from a local MP4 using FFmpeg."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

WEB_MAX_EDGE = 1920
WEB_MAX_PIXELS = 24_000_000
WEB_TIMEOUT = 90


def finite_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("must be a finite number")
    return number


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def decimal_argument(value: float) -> str:
    return format(Decimal(str(value)), "f")


def extract_frames(
    video: Path,
    output_dir: Path,
    *,
    ffmpeg: str = "ffmpeg",
    start: float = 0,
    duration: float | None = None,
    fps: float = 2,
    max_frames: int = 120,
    bounded: bool = False,
) -> dict:
    """Publish a fresh extraction directory and return the ordered frame manifest."""
    if not math.isfinite(start) or start < 0:
        raise ValueError("Start must be finite and at least zero")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("Duration must be finite and positive")
    if not math.isfinite(fps) or fps <= 0 or max_frames < 1:
        raise ValueError("FPS and frame limit must be positive, and FPS must be finite")

    video = video.resolve()
    if video.suffix.lower() != ".mp4" or not video.is_file():
        raise ValueError(f"Expected a local MP4 file: {video}")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    executable = shutil.which(ffmpeg)
    if executable is None:
        raise FileNotFoundError(f"FFmpeg executable not found: {ffmpeg}")
    executable = str(Path(executable).resolve())

    timeout = WEB_TIMEOUT if bounded else None
    probe = subprocess.run([executable, "-version"], capture_output=True, check=True, timeout=timeout)
    version = probe.stdout.decode("utf-8", errors="replace").splitlines()[0]
    with video.open("rb") as source:
        source_sha256 = hashlib.file_digest(source, "sha256").hexdigest()

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".video-frames-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror"]
        filters = f"fps={decimal_argument(fps)}"
        if bounded:
            command += [
                "-protocol_whitelist", "file", "-f", "mov", "-enable_drefs", "0",
                "-max_pixels", str(WEB_MAX_PIXELS), "-threads", "2", "-filter_threads", "2",
            ]
            filters += (
                f",scale=w='min({WEB_MAX_EDGE},iw)':h='min({WEB_MAX_EDGE},ih)'"
                ":force_original_aspect_ratio=decrease"
            )
        command += ["-ss", decimal_argument(start), "-i", str(video)]
        if duration is not None:
            command += ["-t", decimal_argument(duration)]
        command += [
            "-map", "0:V:0",
            "-vf", filters,
            "-frames:v", str(max_frames),
            "-c:v", "png",
            "-pix_fmt", "rgb24",
            "-start_number", "1",
        ]
        if bounded:
            command += ["-threads", "2"]
        command.append(str(staging / "frame_%06d.png"))
        started = perf_counter()
        result = subprocess.run(command, capture_output=True, check=False, timeout=timeout)
        elapsed = perf_counter() - started
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise RuntimeError(f"FFmpeg exited with code {result.returncode}\n{detail}")

        frames = sorted(staging.glob("frame_*.png"))
        if not frames:
            raise ValueError("No video frames were exported. Check the requested interval and FPS.")
        if len(frames) > max_frames or any(path.stat().st_size == 0 for path in frames):
            raise ValueError("FFmpeg output failed frame count or size validation")

        manifest = {
            "schema_version": 1,
            "source": {"video": str(video), "sha256": source_sha256},
            "parameters": {
                "start_seconds": start,
                "duration_seconds": duration,
                "fps": fps,
                "max_frames": max_frames,
            },
            "tool": {"executable": executable, "version": version},
            "frames": [path.name for path in frames],
            "result": {"frame_count": len(frames), "extraction_seconds": round(elapsed, 3)},
        }
        if bounded:
            manifest["parameters"]["max_edge"] = WEB_MAX_EDGE
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(output_dir)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Local MP4 input")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for frames and manifest")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable name or path")
    parser.add_argument("--start", type=finite_number, default=0, help="Start offset in seconds, default 0")
    parser.add_argument("--duration", type=finite_number, help="Optional duration in seconds")
    parser.add_argument("--fps", type=finite_number, default=2, help="Requested sampling rate, default 2 fps")
    parser.add_argument("--max-frames", type=positive_integer, default=120, help="Output limit, default 120 frames")
    args = parser.parse_args()

    try:
        extract_frames(
            args.video, args.output_dir, ffmpeg=args.ffmpeg, start=args.start,
            duration=args.duration, fps=args.fps, max_frames=args.max_frames,
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Video frame extraction failed: {error}", file=sys.stderr)
        return 1

    print(args.output_dir.resolve() / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
