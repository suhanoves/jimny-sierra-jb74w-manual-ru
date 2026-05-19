from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageOps


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def image_paths(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in IMAGE_EXTENSIONS else []

    iterator = path.rglob("*") if recursive else path.iterdir()
    return sorted(
        file_path
        for file_path in iterator
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS
    )


def flatten_to_white(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, "white")
        base.alpha_composite(rgba)
        return base.convert("RGB")
    return image.convert("RGB")


def content_bbox(image: Image.Image, threshold: int) -> tuple[int, int, int, int] | None:
    channels = image.split()
    masks = [channel.point(lambda pixel: 255 if pixel < threshold else 0) for channel in channels]
    return ImageChops.lighter(ImageChops.lighter(masks[0], masks[1]), masks[2]).getbbox()


def save_image(image: Image.Image, path: Path) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp{path.suffix}")
    save_kwargs: dict[str, int] = {}
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs = {"quality": 95, "subsampling": 0}

    image.save(tmp_path, **save_kwargs)
    os.replace(tmp_path, path)


def trim_image(path: Path, padding: int, threshold: int, dry_run: bool) -> tuple[bool, str]:
    with Image.open(path) as original:
        image = flatten_to_white(original)

    bbox = content_bbox(image, threshold)
    if bbox is None:
        return False, f"skip all-white: {path}"

    trimmed = image.crop(bbox)
    padded = ImageOps.expand(trimmed, border=padding, fill="white")

    if not dry_run:
        save_image(padded, path)

    return True, f"{path}: {image.size[0]}x{image.size[1]} -> {padded.size[0]}x{padded.size[1]}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trim near-white whitespace around images and add an even white border."
    )
    parser.add_argument("path", type=Path, help="Image file or folder to process in-place.")
    parser.add_argument("--padding", type=int, default=5, help="White border to add after trimming, in pixels.")
    parser.add_argument(
        "--threshold",
        type=int,
        default=245,
        help="Pixels with all RGB channels at or above this value are treated as white.",
    )
    parser.add_argument("--recursive", action="store_true", help="Process images in nested folders too.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing files.")
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary.")
    args = parser.parse_args()

    if args.padding < 0:
        raise SystemExit("--padding must be non-negative")
    if not 0 <= args.threshold <= 255:
        raise SystemExit("--threshold must be between 0 and 255")
    if not args.path.exists():
        raise SystemExit(f"path does not exist: {args.path}")
    if not args.path.is_dir() and not args.path.is_file():
        raise SystemExit(f"path must be a file or folder: {args.path}")

    paths = image_paths(args.path, args.recursive)
    processed = 0
    skipped = 0

    for path in paths:
        changed, message = trim_image(path, args.padding, args.threshold, args.dry_run)
        if not args.quiet:
            print(message)
        if changed:
            processed += 1
        else:
            skipped += 1

    action = "would process" if args.dry_run else "processed"
    print(f"{action}: {processed}, skipped: {skipped}")


if __name__ == "__main__":
    main()
