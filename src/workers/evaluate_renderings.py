"""Evaluate 3DGS renders against a fixed set of held-out RGB photographs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from statistics import mean


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def load_holdout_list(path: Path) -> list[str]:
    names = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    stems = []
    for name in names:
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError(f"Use only frame stems or filenames in the holdout list: {name}")
        candidate = Path(name)
        stems.append(candidate.stem if candidate.suffix.lower() in IMAGE_EXTENSIONS else name)
    if not stems or len(stems) != len(set(stems)):
        raise ValueError("The holdout list must contain unique frame stems and cannot be empty")
    return stems


def index_images(directory: Path) -> dict[str, Path]:
    images = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if path.stem in images:
            raise ValueError(f"Ambiguous frame stem {path.stem!r} in {directory}")
        images[path.stem] = path
    return images


def load_rgb(path: Path):
    import numpy as np
    from PIL import Image

    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != "RGB" or image.format not in {"JPEG", "PNG"}:
            raise ValueError(f"Expected an RGB PNG or JPEG: {path}")
        return np.array(image), hashlib.sha256(data).hexdigest()


def evaluate_view(stem: str, reference_path: Path, render_path: Path) -> dict:
    import numpy as np
    from skimage.color import rgb2gray
    from skimage.filters import sobel
    from skimage.metrics import peak_signal_noise_ratio, structural_similarity

    reference, reference_hash = load_rgb(reference_path)
    render, render_hash = load_rgb(render_path)
    height, width = reference.shape[:2]
    if reference.shape != render.shape:
        raise ValueError(
            f"Frame {stem} size mismatch: reference {width}x{height}, "
            f"render {render.shape[1]}x{render.shape[0]}"
        )
    if min(height, width) < 7:
        raise ValueError(f"Frame {stem} must be at least 7x7 pixels for SSIM")

    identical = np.array_equal(reference, render)
    reference_gradient = sobel(rgb2gray(reference))
    render_gradient = sobel(rgb2gray(render))
    strong_edges = (reference_gradient >= np.quantile(reference_gradient, 0.9)) & (reference_gradient > 0)
    edge_error = None
    if strong_edges.any():
        edge_error = float(np.abs(reference_gradient[strong_edges] - render_gradient[strong_edges]).mean())
    return {
        "frame": stem,
        "reference": {"file": reference_path.name, "sha256": reference_hash},
        "render": {"file": render_path.name, "sha256": render_hash},
        "width": width,
        "height": height,
        "perfect_match": bool(identical),
        "psnr_db": None if identical else float(peak_signal_noise_ratio(reference, render, data_range=255)),
        "ssim": float(structural_similarity(reference, render, data_range=255, channel_axis=-1)),
        "strong_edge_mae": edge_error,
        "strong_edge_pixel_count": int(strong_edges.sum()),
    }


def evaluate(reference_dir: Path, render_dir: Path, holdout_list: Path) -> dict:
    frames = load_holdout_list(holdout_list)
    references = index_images(reference_dir)
    renders = index_images(render_dir)
    expected = set(frames)
    if missing := expected - references.keys():
        raise ValueError(f"Missing references: {', '.join(sorted(missing))}")
    if expected != renders.keys():
        missing = ", ".join(sorted(expected - renders.keys())) or "none"
        unexpected = ", ".join(sorted(renders.keys() - expected)) or "none"
        raise ValueError(f"Render frames do not match the holdout list. Missing: {missing}. Unexpected: {unexpected}.")

    import skimage

    views = [evaluate_view(stem, references[stem], renders[stem]) for stem in frames]
    perfect_matches = sum(view["perfect_match"] for view in views)
    edge_views = [view for view in views if view["strong_edge_mae"] is not None]
    worst_psnr = min(views, key=lambda view: math.inf if view["perfect_match"] else view["psnr_db"])
    worst_ssim = min(views, key=lambda view: view["ssim"])
    worst_edge = max(edge_views, key=lambda view: view["strong_edge_mae"], default=None)
    return {
        "schema_version": 1,
        "scikit_image_version": skimage.__version__,
        "reference_dir": str(reference_dir.resolve()),
        "render_dir": str(render_dir.resolve()),
        "holdout_list": str(holdout_list.resolve()),
        "metric_settings": {
            "rgb": "Encoded RGB values as stored, same encoding required, with no resizing or color conversion",
            "aggregation": "Arithmetic mean per view with equal weight",
            "psnr_db": "RGB PSNR with data range 255, null denotes positive infinity for an exact match",
            "ssim": "RGB channel-mean SSIM with data range 255 and the default 7×7 window",
            "strong_edge_mae": "Absolute luminance Sobel magnitude error averaged over positive reference gradients at or above the 90th percentile. Null denotes no qualifying edges.",
        },
        "frame_count": len(views),
        "perfect_match_count": perfect_matches,
        "mean": {
            "psnr_db": None if perfect_matches else mean(view["psnr_db"] for view in views),
            "ssim": mean(view["ssim"] for view in views),
            "strong_edge_mae": mean(view["strong_edge_mae"] for view in edge_views) if edge_views else None,
            "views_with_strong_edges": len(edge_views),
        },
        "worst": {
            "psnr_db": {"frame": worst_psnr["frame"], "value": worst_psnr["psnr_db"]},
            "ssim": {"frame": worst_ssim["frame"], "value": worst_ssim["ssim"]},
            "strong_edge_mae": {"frame": worst_edge["frame"], "value": worst_edge["strong_edge_mae"]} if worst_edge else None,
        },
        "views": views,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", required=True, type=Path, help="Prepared geometrically aligned RGB photographs")
    parser.add_argument("--render-dir", required=True, type=Path, help="RGB renders for exactly the held-out views")
    parser.add_argument("--holdout-list", required=True, type=Path, help="UTF-8 list with one frame stem or filename per line")
    parser.add_argument("--output", required=True, type=Path, help="New JSON report path")
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise FileExistsError(f"Report already exists: {args.output}")
        report = evaluate(args.reference_dir, args.render_dir, args.holdout_list)
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)
    except (OSError, ValueError, ImportError) as error:
        print(f"Rendering evaluation failed: {error}", file=sys.stderr)
        return 1

    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
