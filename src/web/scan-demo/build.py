"""Train the two object scans and package a locally browsable demo."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image

from capture import ANGLES, FRONT_COUNT, camera, image_url

HERE = Path(__file__).resolve().parent
STEPS = 2400


def train(root, brush, label, count):
    dest = root / f'{label}-fit'
    dest.mkdir()
    args = [str(brush), str(root / label), '--seed', '42', '--total-steps', str(STEPS),
            '--export-every', str(STEPS), '--max-splats', '85000', '--sh-degree', '2',
            '--ssim-weight', '0.25', '--eval-split-every', str(count + 1),
            '--eval-every', str(STEPS), '--eval-save-to-disk', '--export-path', str(dest)]
    start = perf_counter()
    with (dest / 'brush.log').open('wb') as log:
        subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT)
    seconds = round(perf_counter() - start, 2)
    model = dest / f'export_{STEPS}.ply'
    with model.open('rb') as f:
        for line in f:
            if line.startswith(b'element vertex '):
                splats = int(line.split()[-1])
                break
            if line.strip() == b'end_header':
                raise ValueError(f'No vertices declared in {model}')
        else:
            raise ValueError(f'Invalid PLY {model}')
    evaluated = list((dest / f'eval_{STEPS}').glob('*.png'))
    if [image.name for image in evaluated] != ['000_holdout.png']:
        raise ValueError(f'Unexpected evaluation frames: {evaluated}')
    with model.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return model, evaluated[0], {
        'steps': STEPS, 'seconds': seconds, 'views': count, 'splats': splats,
        'sha256': digest, 'args': args[2:],
    }


def foreground_psnr(reference, candidate, mask):
    if candidate.shape != reference.shape:
        raise ValueError('Holdout and render sizes differ')
    mse = np.mean((reference[mask].astype(float) - candidate[mask]) ** 2)
    return round(10 * math.log10(255**2 / mse), 2) if mse else None


def viewer_settings():
    eye, _ = camera(172.5)
    eye = eye * 1.47
    eye[1] = .41
    return {
        'version': 2,
        'tonemapping': 'linear',
        'highPrecisionRendering': False,
        'background': {'color': [.06, .09, .08]},
        'postEffectSettings': {
            'sharpness': {'enabled': False, 'amount': 0},
            'bloom': {'enabled': False, 'intensity': .1, 'blurLevel': 2},
            'grading': {'enabled': False, 'brightness': 1, 'contrast': 1, 'saturation': 1, 'tint': [1, 1, 1]},
            'vignette': {'enabled': False, 'intensity': .5, 'inner': .75, 'outer': .75, 'curvature': .5},
            'fringing': {'enabled': False, 'intensity': .5},
        },
        'animTracks': [],
        'cameras': [{'initial': {
            'position': eye.tolist(), 'target': [0, .183, 0], 'fov': 42,
        }}],
        'annotations': [],
        'startMode': 'default',
    }


def package_viewer(root, splat_tool, model):
    settings = root / 'viewer-settings.json'
    settings.write_text(json.dumps(viewer_settings(), indent=2))
    # The HTML viewer rotates SOG about +Z on import. Convert the world-up
    # simulation coordinates before encoding to preserve the upright object.
    subprocess.run(['node', str(splat_tool), '--no-tty', '--overwrite',
                    '--viewer-settings', str(settings), str(model), '--rotate', '0,0,180',
                    str(root / 'demo' / 'viewer.html')], check=True)


def write_archive(root):
    with ZipFile(root / 'orbitforge-scan-demo.zip', 'w', ZIP_DEFLATED) as archive:
        for name in ('index.html', 'viewer.html'):
            archive.write(root / 'demo' / name, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='A new directory for captures, training and demo')
    parser.add_argument('--brush', required=True, type=Path)
    parser.add_argument('--splat-tool', required=True, type=Path, help='SplatTransform cli.mjs')
    args = parser.parse_args()
    root = args.output.resolve()
    brush, splat_tool = args.brush.resolve(strict=True), args.splat_tool.resolve(strict=True)
    root.mkdir(parents=True)
    subprocess.run([sys.executable, str(HERE / 'capture.py'), str(root)], check=True)
    release = root / 'demo'
    release.mkdir()
    capture_data = json.loads((root / 'capture.json').read_text())
    rgba = np.asarray(Image.open(root / 'captures' / '000_holdout.png').convert('RGBA'))
    reference = rgba[..., :3]
    visible = rgba[..., 3] > 0
    images = {'reference': image_url(np.where(visible[..., None], reference, 0).astype(np.uint8))}
    report = {'holdout_angle': capture_data['holdoutAngle'], 'resolution': [480, 360], 'results': {}}
    for label, count in [('front', FRONT_COUNT), ('full', len(ANGLES))]:
        model, rendered, stats = train(root, brush, label, count)
        pixels = np.asarray(Image.open(rendered).convert('RGB'))
        stats['foreground_psnr_db'] = foreground_psnr(reference, pixels, visible)
        images[label] = image_url(pixels)
        report['results'][label] = stats
    package_viewer(root, splat_tool, model)
    page = (HERE / 'index.html').read_text(encoding='utf-8')
    replacements = {
        '__STYLE__': (HERE / 'workbench.css').read_text(encoding='utf-8'),
        '__SCRIPT__': (HERE / 'workbench.js').read_text(encoding='utf-8'),
        '__CAPTURE_DATA__': json.dumps(capture_data, separators=(',', ':')),
        '__FIT_DATA__': json.dumps(images, separators=(',', ':')),
    }
    for marker, value in replacements.items():
        page = page.replace(marker, value, 1)
    (release / 'index.html').write_text(page, encoding='utf-8')
    (root / 'training.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    write_archive(root)
    print(json.dumps(report['results'], indent=2))


if __name__ == '__main__':
    main()
