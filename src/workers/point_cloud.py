"""Export a point cloud from one or more ordered photos with offline DA3-BASE."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import struct
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def load_model(model_dir: Path, device: str):
    """Load the local checkpoint once so a caller can reuse it across batches."""
    model_dir = model_dir.resolve()
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    if config.get("model_name") != "da3-base":
        raise ValueError(f"Expected the DA3-BASE checkpoint in {model_dir}")
    if not (model_dir / "model.safetensors").is_file():
        raise FileNotFoundError(f"Missing model.safetensors in {model_dir}")

    from depth_anything_3.api import DepthAnything3

    return DepthAnything3.from_pretrained(str(model_dir), local_files_only=True).to(device).eval()


def count_points(glb: Path) -> int:
    with glb.open("rb") as stream:
        magic, version, size = struct.unpack("<4sII", stream.read(12))
        chunk_size, chunk_type = struct.unpack("<I4s", stream.read(8))
        if (magic, version, size) != (b"glTF", 2, glb.stat().st_size) or chunk_type != b"JSON":
            raise ValueError("DA3 did not export a valid GLB")
        document = json.loads(stream.read(chunk_size))
    return sum(
        document["accessors"][primitive["attributes"]["POSITION"]]["count"]
        for mesh in document.get("meshes", [])
        for primitive in mesh["primitives"]
        if primitive.get("mode") == 0
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def export_point_cloud(
    model,
    images: list[Path],
    output_dir: Path,
    *,
    model_dir: Path,
    device: str,
    process_res: int = 504,
    max_points: int = 200_000,
    with_depth: bool = False,
    calibrations: list[dict] | None = None,
) -> dict:
    """Export a complete batch into a new directory and return its manifest."""
    images = [path.resolve() for path in images]
    if not images or process_res < 1 or max_points < 1:
        raise ValueError("Provide at least one photo and positive resolution and point limits")
    for path in images:
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
            raise ValueError(f"Expected a JPEG or PNG file: {path}")
    camera_inputs = {}
    if calibrations is not None:
        import numpy as np

        camera_inputs = {
            name: np.asarray([calibration[name] for calibration in calibrations], dtype=np.float32)
            for name in ("extrinsics", "intrinsics")
        }
        if (camera_inputs["extrinsics"].shape != (len(images), 4, 4)
                or camera_inputs["intrinsics"].shape != (len(images), 3, 3)):
            raise ValueError("Expected one valid camera calibration per image")

    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    frames = [{"image": str(path), "sha256": sha256_file(path)} for path in images]
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".point-cloud-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        started = perf_counter()
        model.inference(
            [str(path) for path in images],
            process_res=process_res,
            ref_view_strategy="first",
            export_dir=str(staging),
            export_format="glb-depth_vis" if with_depth else "glb",
            show_cameras=False,
            num_max_points=max_points,
            export_kwargs={"glb": {"export_depth_vis": False}},
            **camera_inputs,
        )
        elapsed = perf_counter() - started
        glb = staging / "scene.glb"
        point_count = count_points(glb)
        if not 0 < point_count <= max_points:
            raise ValueError(f"DA3 exported {point_count} points with a limit of {max_points}")

        if with_depth:
            for index, frame in enumerate(frames):
                preview = Path("depth_vis") / f"{index:04d}.jpg"
                if not (staging / preview).is_file() or (staging / preview).stat().st_size == 0:
                    raise ValueError(f"DA3 did not export depth preview for image {index + 1}")
                frame["depth_preview"] = preview.as_posix()

        torch = sys.modules.get("torch")
        manifest = {
            "schema_version": 1,
            "model": "DA3-BASE",
            "model_dir": str(model_dir.resolve()),
            "device": device,
            "runtime": {
                "python": platform.python_version(),
                "pytorch": torch.__version__ if torch else None,
                "cuda": torch.version.cuda if torch else None,
            },
            "frames": frames,
            "parameters": {
                "process_res": process_res,
                "ref_view_strategy": "first",
                "max_points": max_points,
                "with_depth": with_depth,
                "camera_calibration": "virtual-camera-v1" if camera_inputs else "estimated",
            },
            "result": {
                "point_cloud": glb.name,
                "point_count": point_count,
                "bytes": glb.stat().st_size,
                "inference_and_export_seconds": round(elapsed, 3),
                "scale": "relative",
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(output_dir)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path, nargs="+", help="JPEG/PNG photos in capture order")
    parser.add_argument("--model-dir", type=Path, required=True, help="Local DA3-BASE checkpoint directory")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for results")
    parser.add_argument("--device", default="cuda", help="PyTorch device, default cuda")
    parser.add_argument("--process-res", type=positive_integer, default=504, help="DA3 input size, default 504")
    parser.add_argument("--max-points", type=positive_integer, default=200_000, help="GLB point limit, default 200000")
    parser.add_argument("--with-depth", action="store_true", help="Include RGB/depth previews for each photo")
    parser.add_argument("--camera-calibration", type=Path, help="JSON calibration in image order")
    args = parser.parse_args()

    try:
        calibrations = json.loads(args.camera_calibration.read_text(encoding="utf-8")) if args.camera_calibration else None
        model = load_model(args.model_dir, args.device)
        export_point_cloud(
            model,
            args.images,
            args.output_dir,
            model_dir=args.model_dir,
            device=args.device,
            process_res=args.process_res,
            max_points=args.max_points,
            with_depth=args.with_depth,
            calibrations=calibrations,
        )
    except Exception as error:
        print(f"Point cloud export failed: {error}", file=sys.stderr)
        return 1

    print(args.output_dir.resolve() / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
