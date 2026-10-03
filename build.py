"""Build the Snoopy theme and userChrome assets, and package the theme as an .xpi."""

import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).parent
SOURCE = ROOT / "source" / "original-header.png"
GIPHY = ROOT / "source" / "giphy"
THEME_DIR = ROOT / "theme"
HEADER_OUT = THEME_DIR / "images" / "header.png"
ASSETS = ROOT / "userChrome" / "assets"
DIST = ROOT / "dist"

# userChrome assets are rendered at 2x and shown at half size for Retina.
SCALE = 2

# Every animation frame repaints part of the window; cap the frame rate.
MIN_FRAME_MS = 60

# Theme-only fallback (used when userChrome.css is not installed).
HEADER_HEIGHT = 40
LEFT_GAP = 430
RIGHT_GAP = 430

# Regions of the original 2090x70 animation, as (left, top, right, bottom).
TYPING_BOX = (1840, 0, 1962, 70)
CART_BOX = (626, 4, 674, 42)

# Display height in CSS px for each userChrome asset.
ASSET_HEIGHTS = {
    "snoopy-typing": 35,
    "woodstock-cart": 26,
    "snoopy-sleeping": 35,
    "snoopy-dance": 35,
    "woodstock-flying": 22,
    "doghouse-scene": 83,
}

# Always-visible animations get a lower frame rate.
ASSET_MIN_FRAME_MS = {"doghouse-scene": 80}


def load_frames(path):
    im = Image.open(path)
    frames, durations = [], []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        frames.append(im.convert("RGBA"))
        durations.append(int(im.info.get("duration", 100)))
    return frames, durations


def clear_white_background(frame, threshold=235):
    """Make white connected to the image edge transparent, keeping enclosed white."""
    w, h = frame.size
    r, g, b, _ = frame.split()
    near_white = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= threshold else 0)
    for x, y in [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]:
        if near_white.getpixel((x, y)) == 255:
            ImageDraw.floodfill(near_white, (x, y), 128)
    alpha = frame.getchannel("A").copy()
    alpha.paste(0, mask=near_white.point(lambda v: 255 if v == 128 else 0))
    out = frame.copy()
    out.putalpha(alpha)
    return out


def union_bbox(frames):
    box = None
    for f in frames:
        b = f.getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def fit_height(frames, height):
    w, h = frames[0].size
    size = (max(1, round(w * height / h)), height)
    if size == frames[0].size:
        return frames
    return [f.resize(size, Image.LANCZOS) for f in frames]


def merge_still_frames(frames, durations, threshold=16, min_ms=0):
    """Fold invisible (noise-only) changes and frames shorter than min_ms into the previous frame."""
    kept, kept_durations = [frames[0]], [durations[0]]
    for frame, duration in zip(frames[1:], durations[1:]):
        delta = ImageChops.difference(kept[-1], frame).point(lambda v: 255 if v > threshold else 0)
        if kept_durations[-1] >= min_ms and delta.getbbox(alpha_only=False):
            kept.append(frame)
            kept_durations.append(duration)
        else:
            kept_durations[-1] += duration
    return kept, kept_durations


def save_apng(frames, durations, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(frames) == 1:
        frames[0].save(path, optimize=True)
        return
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=0,
        blend=0,
    )


def build_asset(name, frames, durations):
    frames = [clear_white_background(f) for f in frames]
    box = union_bbox(frames)
    frames = fit_height([f.crop(box) for f in frames], ASSET_HEIGHTS[name] * SCALE)
    frames, durations = merge_still_frames(frames, durations, min_ms=ASSET_MIN_FRAME_MS.get(name, MIN_FRAME_MS))
    path = ASSETS / f"{name}.png"
    save_apng(frames, durations, path)
    w, h = frames[0].size
    print(f"  {name}: {len(frames)} frames, {w // SCALE}x{h // SCALE} css px, {path.stat().st_size // 1024} KB")
    return frames, durations


def build_header(source_frames, durations):
    sprites = {
        "left": [clear_white_background(f.crop(TYPING_BOX)) for f in source_frames],
        "right": [clear_white_background(f.crop(CART_BOX)) for f in source_frames],
    }
    sprites["left"] = fit_height(sprites["left"], 38)
    sprites["right"] = fit_height(sprites["right"], 30)
    half = max(LEFT_GAP + sprites["left"][0].width, RIGHT_GAP + sprites["right"][0].width)

    frames = []
    for left, right in zip(sprites["left"], sprites["right"]):
        canvas = Image.new("RGBA", (half * 2, HEADER_HEIGHT), (0, 0, 0, 0))
        canvas.paste(left, (half - LEFT_GAP - left.width, (HEADER_HEIGHT - left.height) // 2))
        canvas.paste(right, (half + RIGHT_GAP, (HEADER_HEIGHT - right.height) // 2))
        frames.append(canvas)
    frames, durations = merge_still_frames(frames, durations)
    save_apng(frames, durations, HEADER_OUT)
    print(f"  theme header: {len(frames)} frames, {frames[0].width}x{frames[0].height}")


def package(theme_dir, dist):
    dist.mkdir(exist_ok=True)
    xpi = dist / "snoopy-vertical.xpi"
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(theme_dir.rglob("*")):
            if f.is_file() and f.name != ".DS_Store":
                zf.write(f, f.relative_to(theme_dir))
    return xpi


def main():
    source_frames, source_durations = load_frames(SOURCE)
    print("theme:")
    build_header(source_frames, source_durations)

    print("userChrome assets:")
    build_asset("snoopy-typing", [f.crop(TYPING_BOX) for f in source_frames], source_durations)
    build_asset("woodstock-cart", [f.crop(CART_BOX) for f in source_frames], source_durations)
    for name in ("snoopy-sleeping", "snoopy-dance", "woodstock-flying", "doghouse-scene"):
        build_asset(name, *load_frames(GIPHY / f"{name}.gif"))

    xpi = package(THEME_DIR, DIST)
    print(f"packaged {xpi.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
