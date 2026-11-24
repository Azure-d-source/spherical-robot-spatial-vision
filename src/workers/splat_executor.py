import hashlib
import json
import logging
from pathlib import Path
from subprocess import TimeoutExpired

from PIL import Image, ImageOps

from .process_group import start_process
from .registration import ExecutionError, SPLAT_RECIPES
from .simulation_camera import frame_calibration

SCRIPT = Path(__file__).with_name("reconstruct_gaussians.py")
POINT_SCRIPT = Path(__file__).with_name("point_cloud.py")
log = logging.getLogger(__name__)


def failure_coverage(lines, frames):
    prefix = "UNREGISTERED_INPUT_INDICES: "
    for line in reversed(lines):
        if not line.startswith(prefix):
            continue
        try:
            missing = json.loads(line.removeprefix(prefix))
        except ValueError:
            return None
        if (isinstance(missing, list)
                and all(type(index) is int and 0 <= index < len(frames) for index in missing)
                and missing == sorted(set(missing))):
            return {
                "registered_images": len(frames) - len(missing),
                "total_images": len(frames),
                "unregistered_frame_ids": [frames[index]["frame_id"] for index in missing],
            }
        return None
    return None


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
    calibrations = [frame_calibration(frame) for frame in job["frames"]]
    return execute_cli(job, data_dir, command, cancelled, calibrations=calibrations if all(calibrations) else None)


def execute_points(job, data_dir, python, model, cancelled):
    if job["recipe_version"] != "v1":
        raise ExecutionError("EXECUTOR_ERROR", "未知的 DA3 配方。")
    expected = len(job["frames"])
    if (job["kind"] == "depth" and expected != 1) or (job["kind"] == "fusion" and expected < 2):
        raise ExecutionError("EXECUTOR_ERROR", "DA3 作业和批次照片张数不匹配。")
    command = [python, str(POINT_SCRIPT), "--model-dir", model, "--device", "cuda", "--with-depth"]
    calibrations = [frame_calibration(frame) for frame in job["frames"]]
    return execute_cli(job, data_dir, command, cancelled,
                       calibrations=calibrations if expected > 1 and all(calibrations) else None)


def execute_cli(job, data_dir, command, cancelled, *, calibrations=None):
    if cancelled():
        return False
    attempt_dir = data_dir / "staging" / job["job_id"] / f"attempt-{job['attempt']}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    files = prepare_inputs(job["frames"], data_dir / "photos", attempt_dir)
    output = attempt_dir / "out"
    command[2:2] = ["--output-dir", str(output)]
    if calibrations:
        calibration_path = attempt_dir / "camera-calibration.json"
        calibration_path.write_text(json.dumps(calibrations), encoding="utf-8")
        command.extend(("--camera-calibration", str(calibration_path)))
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
        with stderr_path.open("rb") as stream:
            stream.seek(max(0, stderr_path.stat().st_size - 4096))
            detail = stream.read().decode("utf-8", errors="replace")
        log.error("CLI exit code %s. See %s", process.returncode, stderr_path)
        lines = detail.splitlines()
        if any(line.startswith("INSUFFICIENT_REGISTRATION:") for line in lines):
            coverage = failure_coverage(lines, job["frames"])
            raise ExecutionError(
                "INSUFFICIENT_REGISTRATION", "配准不足，请补拍清晰、有重叠和位移的机位。", coverage
            )
        if "Shared calibration requires one image size and orientation after resizing:" in detail:
            raise ExecutionError("RESOLUTION_MISMATCH", "校正方向后照片画幅不一致。请统一拍摄方向与画幅。")
        raise ExecutionError("EXECUTOR_ERROR", "作业执行失败，请查看 Worker 日志。")
    return not cancelled()
