from dataclasses import dataclass


@dataclass(frozen=True)
class SplatRecipe:
    steps: int
    required_frames: int | None = None


SPLAT_RECIPES = {
    "v1": SplatRecipe(8000),
    "public-32-v1": SplatRecipe(400, required_frames=32),
}


class ExecutionError(Exception):
    def __init__(self, code: str, message: str, coverage: dict | None = None):
        super().__init__(message)
        self.code = code
        self.coverage = coverage


def registration_coverage(manifest: dict, frame_ids: list[str]) -> dict:
    """Map the CLI's zero-based input positions back to the frozen revision."""
    try:
        colmap = manifest["colmap"]
        frames = manifest["frames"]
        flags = [frame["registered"] for frame in frames]
        missing = [index for index, flag in enumerate(flags) if not flag]
        reported_missing = [frame["input_index"] for frame in colmap["unregistered_frames"]]
        total = len(frame_ids)
        registered = total - len(missing)
        sparse_points = colmap["sparse_points"]
        if (len(flags) != total or any(type(flag) is not bool for flag in flags)
                or colmap["total_images"] != total or colmap["registered_images"] != registered
                or reported_missing != missing or type(sparse_points) is not int):
            raise ValueError("Inconsistent registration summary")
    except (KeyError, TypeError, ValueError) as error:
        raise ExecutionError("INVALID_ARTIFACT", "重建清单中的配准统计无效。") from error

    coverage = {
        "registered_images": registered,
        "total_images": total,
        "unregistered_frame_ids": [frame_ids[index] for index in missing],
    }
    if registered < 3 or sparse_points <= 0:
        raise ExecutionError(
            "INSUFFICIENT_REGISTRATION", "配准不足，请补拍清晰、有重叠和位移的机位。", coverage
        )
    return coverage


def verify_recipe(recipe_version: str, coverage: dict) -> None:
    required = SPLAT_RECIPES[recipe_version].required_frames
    if required is not None and (
        coverage["total_images"] != required or coverage["registered_images"] != required
    ):
        raise ExecutionError(
            "INCOMPLETE_REGISTRATION", f"此配方要求全部 {required} 张照片注册成功。", coverage
        )
