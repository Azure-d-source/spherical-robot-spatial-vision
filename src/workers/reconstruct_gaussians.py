"""Reconstruct a static scene from ordered photos with local COLMAP and Brush."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter


class RegistrationError(ValueError):
    """COLMAP did not yield a component usable by Brush."""

    def __init__(self, message: str, unregistered_indices: list[int]):
        super().__init__(message)
        self.unregistered_indices = unregistered_indices


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def prepare_images(sources: list[Path], directory: Path, long_edge: int) -> tuple[list[dict], tuple[int, int]]:
    from PIL import Image, ImageCms, ImageOps

    directory.mkdir()
    frames = []
    output_size = None
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    for index, source in enumerate(sources, start=1):
        source_bytes = source.read_bytes()
        with Image.open(io.BytesIO(source_bytes)) as original:
            if original.format not in {"JPEG", "PNG"}:
                raise ValueError(f"Expected real JPEG or PNG image content: {source}")
            image = ImageOps.exif_transpose(original)
            width, height = image.size
            scale = long_edge / max(width, height)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            if output_size is None:
                output_size = size
            if size != output_size:
                raise ValueError(
                    f"Shared calibration requires one image size and orientation after resizing: "
                    f"expected {output_size}, got {size} for {source}"
                )

            profile = image.info.get("icc_profile")
            if profile:
                if image.mode in {"P", "RGBA", "RGBX"}:
                    image = image.convert("RGB")
                try:
                    image = ImageCms.profileToProfile(image, io.BytesIO(profile), srgb, outputMode="RGB")
                except (OSError, ImageCms.PyCMSError) as error:
                    raise ValueError(f"Cannot convert embedded color profile to sRGB: {source}") from error
            else:
                image = image.convert("RGB")
            if image.size != size:
                image = image.resize(size, Image.Resampling.LANCZOS)
            name = f"{index:05d}.png"
            image.save(directory / name, icc_profile=srgb.tobytes())
            frames.append({
                "source": str(source),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "prepared": f"images/{name}",
            })

    assert output_size is not None
    return frames, output_size


def register_images(staging: Path, frames: list[dict]) -> dict:
    import pycolmap

    database = staging / "colmap.db"
    images = staging / "images"
    with TemporaryDirectory(prefix="mapper-", dir=staging) as mapper_directory:
        pycolmap.extract_features(
            database, images,
            camera_mode=pycolmap.CameraMode.SINGLE,
            reader_options=pycolmap.ImageReaderOptions(camera_model="SIMPLE_RADIAL"),
            device=pycolmap.Device.cpu,
        )
        pycolmap.match_exhaustive(database, device=pycolmap.Device.cpu)
        models = pycolmap.incremental_mapping(database, images, mapper_directory)
        if not models:
            raise RegistrationError(
                "COLMAP registered no model. Check image overlap, sharpness and view translation.",
                list(range(len(frames))),
            )
        largest = max(models.values(), key=lambda model: (model.num_reg_images(), model.num_points3D()))
        registered = {largest.image(image_id).name for image_id in largest.reg_image_ids()}
        if largest.num_reg_images() < 3 or largest.num_points3D() == 0:
            raise RegistrationError(
                f"Largest COLMAP model has {largest.num_reg_images()} registered photos "
                f"and {largest.num_points3D()} sparse points. Add intermediate views and retry.",
                [index for index, frame in enumerate(frames) if Path(frame["prepared"]).name not in registered],
            )
        model_dir = staging / "sparse" / "0"
        model_dir.mkdir(parents=True)
        largest.write(model_dir)
        point_count = largest.num_points3D()
        model_count = len(models)

    unregistered = []
    for input_index, frame in enumerate(frames):
        frame["registered"] = Path(frame["prepared"]).name in registered
        if not frame["registered"]:
            unregistered.append({
                "input_index": input_index,
                "prepared": frame["prepared"],
                "source_sha256": frame["source_sha256"],
            })
    return {
        "version": pycolmap.__version__,
        "camera_model": "SIMPLE_RADIAL",
        "shared_camera": True,
        "matching": "CPU SIFT and exhaustive matching",
        "component_count": model_count,
        "registered_images": len(frames) - len(unregistered),
        "total_images": len(frames),
        "unregistered_frames": unregistered,
        "sparse_points": point_count,
        "selected_model": "sparse/0",
    }


def run_tool(command: list[str], log: Path) -> None:
    with log.open("wb") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        detail = log.read_text(encoding="utf-8", errors="replace")[-2000:].strip()
        raise RuntimeError(f"{Path(command[0]).name} failed with exit code {result.returncode}\n{detail}")


def read_gaussian_count(ply: Path) -> int:
    with ply.open("rb") as stream:
        if stream.readline().strip() != b"ply":
            raise ValueError(f"Expected a PLY file: {ply}")
        count = 0
        fields = set()
        for line in stream:
            line = line.strip()
            if line.startswith(b"element vertex "):
                count = int(line.split()[-1])
            elif line.startswith(b"property "):
                fields.add(line.split()[-1])
            elif line == b"end_header":
                required = {b"x", b"y", b"z", b"opacity", b"scale_0", b"rot_0", b"f_dc_0"}
                if count > 0 and required <= fields and stream.read(1):
                    return count
                break
    raise ValueError(f"Brush did not export a populated Gaussian PLY: {ply}")


def reconstruct(args: argparse.Namespace) -> Path:
    sources = [path.resolve() for path in args.images]
    if len(set(sources)) < 3 or len(set(sources)) != len(sources):
        raise ValueError("Provide at least three different JPEG or PNG photos in capture order")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)

    brush = args.brush_exe.resolve(strict=True)
    sog_cli = args.splat_transform_cli.resolve(strict=True) if args.splat_transform_cli else None
    node = shutil.which("node") if sog_cli else None
    if sog_cli and not node:
        raise FileNotFoundError("Install Node.js or add it to PATH to export SOG")

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".gaussian-reconstruction-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        start = perf_counter()
        frames, size = prepare_images(sources, staging / "images", args.long_edge)
        timings = {"prepare_images": round(perf_counter() - start, 3)}

        print(f"Registering {len(frames)} prepared images at {size[0]}×{size[1]}", flush=True)
        start = perf_counter()
        registration = register_images(staging, frames)
        timings["colmap"] = round(perf_counter() - start, 3)

        print(f"Registered {registration['registered_images']}/{len(frames)} images. Running Brush.", flush=True)
        brush_dir = staging / "brush"
        brush_dir.mkdir()
        start = perf_counter()
        run_tool([
            str(brush), str(staging),
            "--total-steps", str(args.steps),
            "--max-resolution", str(args.long_edge),
            "--max-splats", str(args.max_splats),
            "--export-every", str(args.steps),
            "--export-path", str(brush_dir),
        ], staging / "brush.log")
        brush_ply = brush_dir / f"export_{args.steps}.ply"
        gaussian_count = read_gaussian_count(brush_ply)
        ply = staging / "scene.ply"
        brush_ply.rename(ply)
        brush_dir.rmdir()
        timings["brush_and_export"] = round(perf_counter() - start, 3)

        artifacts = {"ply": {"path": ply.name, "bytes": ply.stat().st_size, "gaussians": gaussian_count}}
        if sog_cli:
            print("Converting the full Gaussian model to SOG.", flush=True)
            start = perf_counter()
            sog = staging / "scene.sog"
            run_tool([node, str(sog_cli), "-g", args.sog_gpu, str(ply), str(sog)], staging / "splat-transform.log")
            with zipfile.ZipFile(sog) as archive:
                metadata = json.loads(archive.read("meta.json"))
            if metadata.get("count") != gaussian_count:
                raise ValueError("SOG Gaussian count differs from source PLY")
            artifacts["sog"] = {"path": sog.name, "bytes": sog.stat().st_size, "gaussians": gaussian_count}
            timings["sog"] = round(perf_counter() - start, 3)

        manifest = {
            "schema_version": 1,
            "frames": frames,
            "parameters": {
                "prepared_width": size[0],
                "prepared_height": size[1],
                "prepared_color_profile": "sRGB",
                "brush_steps": args.steps,
                "brush_max_splats": args.max_splats,
            },
            "colmap": registration,
            "brush_executable": str(brush),
            "splat_transform_cli": str(sog_cli) if sog_cli else None,
            "seconds_by_stage": timings,
            "artifacts": artifacts,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(output_dir)
    return output_dir / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path, help="JPEG or PNG photos in capture order")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory for scene files and manifest")
    parser.add_argument("--brush-exe", required=True, type=Path, help="Path to the local Brush executable")
    parser.add_argument("--long-edge", type=positive_integer, default=1200, help="Resize photos to this long edge")
    parser.add_argument("--steps", type=positive_integer, default=8000, help="Brush optimization steps")
    parser.add_argument("--max-splats", type=positive_integer, default=300_000, help="Brush Gaussian budget")
    parser.add_argument("--splat-transform-cli", type=Path, help="Optional local SplatTransform cli.mjs to export SOG")
    parser.add_argument("--sog-gpu", default="0", help="SplatTransform GPU index or cpu")
    args = parser.parse_args()

    try:
        manifest = reconstruct(args)
    except RegistrationError as error:
        print(f"INSUFFICIENT_REGISTRATION: {error}", file=sys.stderr)
        print(f"UNREGISTERED_INPUT_INDICES: {json.dumps(error.unregistered_indices)}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"3DGS reconstruction failed: {error}", file=sys.stderr)
        return 1

    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
