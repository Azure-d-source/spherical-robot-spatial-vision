"""Calibration for the fixed-resolution virtual camera used by the workbench."""

import math
import re

LAYOUT_PATTERN = re.compile(r"^\[(sim-v1:-?[0-9]+,-?[0-9]+,-?[0-9]+)\] ")
CAMERA_PATTERN = re.compile(r"^\[sim-v1:(-?[0-9]+),(-?[0-9]+),-?[0-9]+\] .+ @cam:(-?[0-9]+),([0-9]+),([0-9]+)$")
WIDTH, HEIGHT = 960, 720
FOCAL_LENGTH = HEIGHT / 2 / math.tan(math.radians(40 / 2))


def frame_calibration(frame):
    """Return OpenCV world-to-camera calibration for a tagged virtual PNG."""
    match = CAMERA_PATTERN.fullmatch(frame.get("view_label") or "")
    if not match or (frame.get("width"), frame.get("height")) != (WIDTH, HEIGHT):
        return None
    x, z, azimuth, elevation, distance_cm = map(int, match.groups())
    if not (-70 <= x <= 70 and -70 <= z <= 70 and -180 <= azimuth <= 180
            and 4 <= elevation <= 85 and 350 <= distance_cm <= 800):
        return None
    heading = math.radians(azimuth)
    angle = math.radians(elevation)
    sin_h, cos_h = math.sin(heading), math.cos(heading)
    sin_a, cos_a = math.sin(angle), math.cos(angle)
    distance = distance_cm / 100
    horizontal = distance * cos_a
    center = (x / 100 + horizontal * sin_h, 1.05 + distance * sin_a, z / 100 + horizontal * cos_h)
    rotation = (
        (cos_h, 0, -sin_h),
        (sin_h * sin_a, -cos_a, cos_h * sin_a),
        (-sin_h * cos_a, -sin_a, -cos_h * cos_a),
    )
    extrinsics = [[*axis, -sum(a * b for a, b in zip(axis, center, strict=True))] for axis in rotation]
    extrinsics.append([0, 0, 0, 1])
    return {
        "center": center,
        "target": (x / 100, 1.05, z / 100),
        "extrinsics": extrinsics,
        "intrinsics": [[FOCAL_LENGTH, 0, WIDTH / 2], [0, FOCAL_LENGTH, HEIGHT / 2], [0, 0, 1]],
    }
