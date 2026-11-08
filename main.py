"""Changeling Tiresias: FaceApp-style gender swap.

    python main.py                      # the window
    python main.py photo.jpg            # swap, writes photo_swapped.jpg
    python main.py photo.jpg -o out.jpg --to female --strength 1.2 --quality 0
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

QUALITY_STEPS = {'fast': 0, 'balanced': 100, 'best': 250}


def read_rgb(path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f'Could not read image: {path}')
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def write_rgb(path, image):
    ok, buf = cv2.imencode(Path(path).suffix or '.jpg', cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:
        raise SystemExit(f'Could not write image: {path}')
    buf.tofile(str(path))


def run_cli(args):
    from genderswap import GenderSwapper

    swapper = GenderSwapper(args.device)
    steps = QUALITY_STEPS[args.quality] if args.steps is None else args.steps

    def progress(i, total, loss):
        print(f'\r  tuning {i}/{total}  loss {loss:.4f}', end='', flush=True)

    for path in args.images:
        src = Path(path)
        print(f'{src.name}:')
        output = 'photo' if (args.whole_photo or args.keep_hair) else 'frame'
        result = swapper.swap(read_rgb(src), args.to, args.strength, steps, progress, keep_hair=args.keep_hair, output=output)
        if steps:
            print()
        out = Path(args.output) if args.output and len(args.images) == 1 else \
            src.with_name(f'{src.stem}_swapped{src.suffix}')
        write_rgb(out, result.image)
        print(f'  detected {result.detected} -> {result.target}, saved {out}')
        if args.save_crops:
            strip = np.concatenate([result.aligned, result.reconstruction, result.edited], axis=1)
            write_rgb(out.with_name(f'{out.stem}_crops.jpg'), strip)


def run_ui(args):
    from genderswap import GenderSwapper
    from window import Window

    Window(GenderSwapper, args.device).run()


def main():
    parser = argparse.ArgumentParser(description='Changeling Tiresias: FaceApp-style gender swap (StyleGAN2 + e4e + PTI).')
    parser.add_argument('images', nargs='*', help='Input photo(s). Omit to open the window.')
    parser.add_argument('-o', '--output', help='Output path (single input only).')
    parser.add_argument('--to', choices=['auto', 'female', 'male'], default='auto')
    parser.add_argument('--strength', type=float, default=1.0)
    parser.add_argument('--quality', choices=list(QUALITY_STEPS), default='balanced',
                        help='fast = encoder only; balanced/best = also fine-tune on the face (keeps identity).')
    parser.add_argument('--steps', type=int, help='Override the number of fine-tuning steps.')
    parser.add_argument('--save-crops', action='store_true', help='Also save aligned input / reconstruction / edit.')
    parser.add_argument('--whole-photo', action='store_true',
                        help='Paste the swap back into the whole photo (default: just the swapped face frame).')
    parser.add_argument('--keep-hair', action='store_true',
                        help='Whole photo, but only the face changes; the photo keeps its own hair.')
    parser.add_argument('--device', help='cuda or cpu (default: cuda if available).')
    parser.add_argument('--download-models', action='store_true', help='Download any missing models and exit.')
    args = parser.parse_args()

    if args.download_models:
        from genderswap import weights
        weights.ensure_all()
    elif args.images:
        run_cli(args)
    else:
        run_ui(args)


if __name__ == '__main__':
    main()
