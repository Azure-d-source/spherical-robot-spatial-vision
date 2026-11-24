import hashlib
from pathlib import Path
from subprocess import TimeoutExpired

from PIL import Image, ImageOps

from .process_group import start_process
from .registration import ExecutionError, SPLAT_RECIPES

SCRIPT = Path(__file__).with_name("reconstruct_gaussians.py")
POINT_SCRIPT = Path(__file__).with_name("point_cloud.py")


def prepare_inputs(frames, photos, attempt_dir):
    inputs = attempt_dir / "inputs"
    inputs.mkdir()
    files = []
    for index, frame in enumerate(frames):
        name = frame["filename"]
        source = photos / name
        if source.resolve().parent != photos or not source.is_file():
            raise ExecutionError("EXECUTOR_ERROR", "找不到批次原图。")
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != frame["sha256"]:
                raise ExecutionError("EXECUTOR_ERROR", "批次原图的哈希不匹配。")
        if source.suffix == ".webp":
            converted = inputs / f"{index:06d}.png"
            with Image.open(source) as image:
                ImageOps.exif_transpose(image).convert("RGB").save(converted)
            source = converted
        files.append(source)
    return files


def execute(job, data_dir, python, brush, splat_transform, cancelled):
    recipe = SPLAT_RECIPES.get(job["recipe_version"])
    if recipe is None:
        raise ExecutionError("EXECUTOR_ERROR", "未知的 3DGS 配方。")
    command = [python, str(SCRIPT), "--brush-exe", brush, "--steps", str(recipe.steps)]
    if splat_transform:
        command.extend(("--splat-transform-cli", splat_transform))
    return execute_cli(job, data_dir, command, cancelled)


def execute_points(job, data_dir, python, model, cancelled):
    if job["recipe_version"] != "v1":
        raise ExecutionError("EXECUTOR_ERROR", "未知的 DA3 配方。")
    expected = len(job["frames"])
    if (job["kind"] == "depth" and expected != 1) or (job["kind"] == "fusion" and expected < 2):
        raise ExecutionError("EXECUTOR_ERROR", "DA3 作业和批次照片张数不匹配。")
    command = [python, str(POINT_SCRIPT), "--model-dir", model, "--device", "cuda", "--with-depth"]
    return execute_cli(job, data_dir, command, cancelled)


def execute_cli(job, data_dir, command, cancelled):
    if cancelled():
        return False
    attempt_dir = data_dir / "staging" / job["job_id"] / f"attempt-{job['attempt']}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    files = prepare_inputs(job["frames"], data_dir / "photos", attempt_dir)
    output = attempt_dir / "out"
    command[2:2] = ["--output-dir", str(output)]
    command.extend(map(str, files))
    if cancelled():
        return False

    stderr_path = attempt_dir / "stderr.log"
    with (attempt_dir / "stdout.log").open("wb") as stdout, stderr_path.open("wb") as stderr:
        with start_process(command, stdout, stderr) as process:
            while process.poll() is None:
                if cancelled():
                    return False
                try:
                    process.wait(timeout=0.25)
                except TimeoutExpired:
                    continue

    if process.returncode:
        with stderr_path.open("rb") as log:
            log.seek(max(0, stderr_path.stat().st_size - 4096))
            detail = log.read().decode("utf-8", errors="replace")
        if any(line.startswith("INSUFFICIENT_REGISTRATION:") for line in detail.splitlines()):
            code = "INSUFFICIENT_REGISTRATION"
        elif "Shared calibration requires one image size and orientation after resizing:" in detail:
            code = "RESOLUTION_MISMATCH"
        else:
            code = "EXECUTOR_ERROR"
        raise ExecutionError(code, str(stderr_path))
    return not cancelled()
