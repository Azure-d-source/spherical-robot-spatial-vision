"""Validate and prepare a publication snapshot for either workbench API."""

import json
import shutil
import struct

from PIL import Image

from ..workers.point_cloud import count_points
from ..workers.registration import ExecutionError, SPLAT_RECIPES, registration_coverage, verify_recipe

ARTIFACT_TYPES = {
    "scene.ply": "application/octet-stream",
    "scene.sog": "application/octet-stream",
    "scene.glb": "model/gltf-binary",
    "manifest.json": "application/json",
}


def read_manifest(output):
    try:
        path = output / "manifest.json"
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Unexpected manifest")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ExecutionError("INVALID_ARTIFACT", "无法读取作业清单。") from error
    if not isinstance(manifest, dict):
        raise ExecutionError("INVALID_ARTIFACT", "作业清单格式无效。")
    return manifest


def stage_splat(output, snapshot, manifest, frames, recipe):
    frame_ids = [frame["frame_id"] for frame in frames]
    coverage = registration_coverage(manifest, frame_ids)
    verify_recipe(recipe, coverage)
    names = ["scene.ply"]
    if (output / "scene.sog").is_file():
        names.append("scene.sog")
    for name in names:
        path = output / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ExecutionError("INVALID_ARTIFACT", f"重建产物缺失或无效。{name}")
        shutil.copyfile(path, snapshot / name)
    return {"registration": coverage}, [{"filename": name} for name in names], {
        "registration": coverage, "seconds_by_stage": manifest.get("seconds_by_stage", {}),
        "viewer_camera": manifest["colmap"].get("viewer_camera"),
    }


def stage_points(output, snapshot, manifest, frames):
    glb = output / "scene.glb"
    files = [{"filename": glb.name}]
    try:
        result = manifest["result"]
        inputs = manifest["frames"]
        if glb.is_symlink() or len(inputs) != len(frames):
            raise ValueError("Unexpected GLB or manifest frame count")
        points = count_points(glb)
        if points <= 0 or result["point_count"] != points or result["point_cloud"] != glb.name:
            raise ValueError("Point count or filename mismatch")
        shutil.copyfile(glb, snapshot / glb.name)
        for index, (frame, entry) in enumerate(zip(frames, inputs, strict=True)):
            relative = f"depth_vis/{index:04d}.jpg"
            if entry["depth_preview"] != relative:
                raise ValueError("Unexpected depth preview path")
            source = output / relative
            if source.resolve() != source:
                raise ValueError("Unexpected depth preview link")
            with Image.open(source, formats=("JPEG",)) as preview:
                preview.load()
            filename = f"depth-{index:04d}.jpg"
            shutil.copyfile(source, snapshot / filename)
            files.append({"filename": filename, "frame_id": frame["frame_id"]})
    except (OSError, KeyError, TypeError, ValueError, struct.error) as error:
        raise ExecutionError("INVALID_ARTIFACT", "点云或深度预览未通过发布校验。") from error
    return {}, files, {
        "model": manifest.get("model"), "runtime": manifest.get("runtime"),
        "parameters": manifest.get("parameters"), "result": result,
    }


def prepare_result(output, snapshot, frames, row):
    manifest = read_manifest(output)
    if row["kind"] == "splat":
        if row["recipe_version"] not in SPLAT_RECIPES:
            raise ExecutionError("UNKNOWN_RECIPE", "3DGS 配方版本不可用。")
        fields, files, metadata = stage_splat(output, snapshot, manifest, frames, row["recipe_version"])
    else:
        fields, files, metadata = stage_points(output, snapshot, manifest, frames)

    for file in files:
        file["size_bytes"] = (snapshot / file["filename"]).stat().st_size
    public_manifest = {
        "job_id": row["job_id"], "revision_id": row["revision_id"],
        "recipe_version": row["recipe_version"], "kind": row["kind"],
        "frames": [{"frame_id": frame["frame_id"], "sha256": frame["sha256"]} for frame in frames],
        **metadata,
        "artifacts": files,
    }
    published_manifest = snapshot / "manifest.json"
    published_manifest.write_text(json.dumps(public_manifest, indent=2), encoding="utf-8")
    files.append({"filename": published_manifest.name, "size_bytes": published_manifest.stat().st_size})
    return {**fields, "artifacts": [
        {**file, "url": f"/api/artifacts/{row['job_id']}/{file['filename']}"} for file in files
    ]}
