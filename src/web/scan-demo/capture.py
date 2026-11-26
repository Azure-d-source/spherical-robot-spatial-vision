"""Render the demo's RGB-D frames and prepare two calibrated Brush datasets."""

import argparse
import base64
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

WIDTH, HEIGHT = 480, 360
FOV = 35
FOCAL = HEIGHT / (2 * math.tan(math.radians(FOV / 2)))
TARGET = np.array([0, 0.183, 0])
VOXEL = 0.006
ANGLES = list(range(-60, 300, 15))
FRONT_COUNT = 9
TEST_ANGLE = 172.5
DEPTH_LIMITS = (0.48, 1.08)

# Geometry of the fictional R7 module. Front faces +Z, up is +Y.
PARTS = [
    ('box', (0, .173, 0), (.205, .127, .163), 'shell'),
    ('box', (0, .064, 0), (.213, .039, .171), 'base'),
    ('box', (0, .295, 0), (.185, .025, .150), 'cap'),
    ('box', (0, .311, -.02), (.115, .018, .090), 'rib'),
    ('sphere', (0, .328, -.02), (.062, .039, .056), 'lens'),
    ('box', (0, .184, .165), (.142, .078, .016), 'trim'),
    ('box', (0, .189, .182), (.116, .048, .003), 'screen'),
    ('sphere', (-.169, .197, .166), (.019, .019, .013), 'led'),
    ('sphere', (.169, .197, .166), (.019, .019, .013), 'led'),
    ('box', (0, .183, -.169), (.135, .071, .012), 'trim'),
    ('box', (0, .184, -.183), (.118, .056, .003), 'badge'),
]
for side in (-1, 1):
    PARTS.extend([
        ('box', (side * .154, .024, .119), (.037, .024, .042), 'rib'),
        ('box', (side * .154, .024, -.119), (.037, .024, .042), 'rib'),
        ('box', (side * .207, .156, 0), (.009, .049, .114), 'vent'),
        ('box', (side * .207, .231, .027), (.013, .026, .038), 'cap'),
    ])


def camera(angle):
    radians = math.radians(angle)
    eye = np.array([.79 * math.sin(radians), .265, .79 * math.cos(radians)])
    forward = TARGET - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    return eye, np.stack([right, down, forward])


def surface_color(material, p, n):
    x, y, z = p.T
    colors = {
        'shell': (201, 78, 48), 'cap': (244, 124, 67),
        'base': (52, 66, 70), 'rib': (37, 49, 52),
        'lens': (27, 130, 130), 'trim': (33, 46, 52),
        'screen': (24, 65, 72), 'led': (119, 247, 222),
        'badge': (246, 198, 76), 'vent': (50, 57, 60),
    }
    color = np.full((len(p), 3), colors[material], dtype=float)
    if material == 'screen':
        signal = (.007 > np.abs(y - (.190 + .022 * np.sin(x * 82)))) & (np.abs(x) < .093)
        color[signal] = (94, 248, 215)
    if material == 'vent':
        color[(np.mod(z + .115, .027) < .007) & (np.abs(z) < .089)] *= .36
    if material == 'badge':
        # Block lettering read from behind, with caution stripes along the edges.
        u = np.floor((-x + .076) / .014).astype(int)
        v = np.floor((.226 - y) / .012).astype(int)
        letters = np.array([list(row) for row in (
            '11110011111', '10001000001', '10001000010',
            '11110000100', '10100001000', '10010010000', '10001010000',
        )]) == '1'
        inside = (u >= 0) & (u < letters.shape[1]) & (v >= 0) & (v < letters.shape[0])
        ink = np.zeros(len(p), dtype=bool)
        ink[inside] = letters[v[inside], u[inside]]
        ink |= (np.abs(x) > .091) & (np.mod(-x + y, .027) < .012)
        color[ink] = (40, 40, 40)
    grain = 1 + .035 * np.sin(293 * x + 93 * y) * np.sin(241 * z - 82 * y)
    light = .62 + .29 * np.maximum(0, n @ np.array([-.46, .78, .42]))
    light += .18 * np.maximum(0, n @ np.array([.56, .36, -.72]))
    return np.clip(color * (grain * light)[:, None], 0, 255).astype(np.uint8)


def render(angle):
    eye, rotation = camera(angle)
    u, v = np.meshgrid(np.arange(WIDTH) + .5, np.arange(HEIGHT) + .5)
    bearings = np.stack([(u - WIDTH / 2) / FOCAL, (v - HEIGHT / 2) / FOCAL,
                         np.ones_like(u)], axis=-1).reshape(-1, 3)
    rays = bearings @ rotation
    depth = np.full(len(rays), np.inf)
    rgba = np.zeros((len(rays), 4), dtype=np.uint8)
    for shape, center, radius, material in PARTS:
        center, radius = np.array(center), np.array(radius)
        if shape == 'box':
            direction = np.where(np.abs(rays) < 1e-10, 1e-10, rays)
            lo, hi = (center - radius - eye) / direction, (center + radius - eye) / direction
            near = np.minimum(lo, hi)
            axis = near.argmax(axis=1)
            distance = near.max(axis=1)
            hit = (distance > 0) & (distance < depth) & (distance <= np.maximum(lo, hi).min(axis=1))
            normal = -np.eye(3)[axis[hit]] * np.sign(rays[hit, axis[hit]])[:, None]
        else:
            origin, ray = (eye - center) / radius, rays / radius
            a, b = (ray * ray).sum(axis=1), ray @ origin
            delta = b * b - a * (origin @ origin - 1)
            distance = (-b - np.sqrt(np.maximum(0, delta))) / a
            hit = (distance > 0) & (distance < depth) & (delta >= 0)
            normal = (eye + rays[hit] * distance[hit, None] - center) / radius**2
            normal /= np.linalg.norm(normal, axis=1)[:, None]
        depth[hit] = distance[hit]
        rgba[hit, :3] = surface_color(material, eye + rays[hit] * distance[hit, None], normal)
        rgba[hit, 3] = 255
    depth[~np.isfinite(depth)] = 0
    return eye, rotation, rgba.reshape(HEIGHT, WIDTH, 4), depth.reshape(HEIGHT, WIDTH)


def image_url(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, 'WEBP', quality=89, method=5)
    return 'data:image/webp;base64,' + base64.b64encode(stream.getvalue()).decode()


def measure_frame(angle, path):
    eye, rotation, rgba, depth = render(angle)
    Image.fromarray(rgba).save(path)
    mm = np.rint(depth * 1000).astype(np.uint16)
    Image.fromarray(mm).save(path.with_name(path.stem + '-mm.png'))
    v, u = np.nonzero(mm[::3, ::3])
    v, u = v * 3, u * 3
    z = mm[v, u] / 1000
    # Back-project the sampled depth pixels using the actual camera export.
    xyz_cam = np.column_stack(((u + .5 - WIDTH / 2) * z / FOCAL,
                               (v + .5 - HEIGHT / 2) * z / FOCAL, z))
    world = eye + xyz_cam @ rotation
    projected = (world - eye) @ rotation.T
    np.testing.assert_allclose(projected, xyz_cam, atol=1e-12)
    # Use the same metre grid in Python and the workbench.
    xyz_mm = np.rint(world * 1000).astype(np.int16)
    _, first = np.unique(xyz_mm // round(VOXEL * 1000), axis=0, return_index=True)
    rgb = rgba[v, u, :3][first]
    samples = np.column_stack((xyz_mm[first], rgb)).astype('<i2')

    stops = np.array([[240, 198, 114], [54, 193, 160], [82, 102, 190]])
    t = np.clip((depth - DEPTH_LIMITS[0]) / (DEPTH_LIMITS[1] - DEPTH_LIMITS[0]), 0, 1)
    colors = np.stack([np.interp(t, [0, .5, 1], stops[:, ch]) for ch in range(3)], axis=-1)
    tint = np.dstack((colors.astype(np.uint8), rgba[..., 3]))
    return samples, {
        'angle': angle, 'eye': eye.tolist(), 'rotation': rotation.tolist(),
        'rgb': image_url(rgba), 'depth': image_url(tint),
        'samples': base64.b64encode(samples.tobytes()).decode(),
        'min': int(mm[mm > 0].min()), 'max': int(mm.max()),
    }


def dataset(root, captures, frames, samples):
    images, sparse = root / 'images', root / 'sparse' / '0'
    images.mkdir(parents=True)
    sparse.mkdir(parents=True)
    (sparse / 'cameras.txt').write_text(
        f'1 PINHOLE {WIDTH} {HEIGHT} {FOCAL} {FOCAL} {WIDTH / 2} {HEIGHT / 2}\n')
    records = []
    for image_id, (name, frame) in enumerate(frames, start=1):
        (images / name).write_bytes((captures / name).read_bytes())
        rotation, eye = np.asarray(frame['rotation']), np.asarray(frame['eye'])
        x, y, z, w = Rotation.from_matrix(rotation).as_quat()
        pose = ' '.join(f'{v:.12g}' for v in [w, x, y, z, *(-rotation @ eye)])
        records.append(f'{image_id} {pose} 1 {name}\n\n')
    (sparse / 'images.txt').write_text(''.join(records))
    merged = np.concatenate(samples)
    _, indices = np.unique(merged[:, :3] // round(VOXEL * 1000), axis=0, return_index=True)
    with (sparse / 'points3D.txt').open('w') as f:
        for point_id, (x, y, z, r, g, b) in enumerate(merged[indices], start=1):
            f.write(f'{point_id} {x/1000} {y/1000} {z/1000} {r} {g} {b} 0\n')
    return int(len(indices))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    out = args.out
    captures = out / 'captures'
    captures.mkdir(parents=True)
    all_frames, all_samples = [], []
    for index, angle in enumerate([TEST_ANGLE, *ANGLES]):
        name = '000_holdout.png' if index == 0 else f'{index:03}_capture.png'
        samples, frame = measure_frame(angle, captures / name)
        all_frames.append((name, frame))
        all_samples.append(samples)
    counts = {}
    for key, count in [('front', FRONT_COUNT), ('full', len(ANGLES))]:
        counts[key] = dataset(out / key, captures, all_frames[:count + 1], all_samples[1:count + 1])
    (out / 'capture.json').write_text(json.dumps({
        'frames': [frame for _, frame in all_frames[1:]], 'holdout': all_frames[0][1]['rgb'],
        'holdoutAngle': TEST_ANGLE, 'frontCount': FRONT_COUNT, 'counts': counts,
        'voxelMM': round(VOXEL * 1000), 'fov': FOV, 'width': WIDTH, 'height': HEIGHT,
        'focal': FOCAL, 'depthLimits': DEPTH_LIMITS, 'targetY': float(TARGET[1]),
    }))
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
