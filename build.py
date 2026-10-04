"""Build the Snoopy theme and userChrome assets, and package the theme as an .xpi."""

import zipfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

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

# README showcase renders, in px.
SHOWCASE = ROOT / "docs" / "showcase"
SHOWCASE_HEIGHT = 120
SHOWCASE_HEIGHTS = {"woodstock-cart": 90, "woodstock-flying": 90, "doghouse-scene": 160}
PAPER = (251, 245, 230, 255)

# Assets kept in their original colors instead of black-and-white line art.
KEEP_COLOR = {"woodstock-cart"}

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


def ramp(low, high):
    return lambda v: 0 if v <= low else 255 if v >= high else round(255 * (v - low) / (high - low))


def _flatten(frame, alpha):
    flat = Image.new("RGB", frame.size, "white")
    flat.paste(frame, mask=alpha)
    return flat


def _boundaries(index_map):
    out = Image.new("L", index_map.size, 0)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        moved = ImageChops.offset(index_map, dx, dy)
        out = ImageChops.lighter(out, ImageChops.difference(index_map, moved).point(lambda v: 255 if v else 0))
    return out


def ink(frames, colors=6):
    """Notion-style line art: keep the black ink, outline color regions, fill with white.

    Each frame is reduced to a few flat color regions (one palette shared by
    all frames so lines don't flicker) and a line is drawn where regions meet.
    Peanuts linework is dark and unsaturated, so it is kept; colored fills
    (red doghouse, yellow Woodstock) turn white. Run after resizing so line
    weight matches across assets.
    """
    first_alpha = frames[0].getchannel("A").point(lambda v: 255 if v > 100 else 0)
    palette = _flatten(frames[0], first_alpha).quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    out = []
    for frame in frames:
        alpha = frame.getchannel("A").point(lambda v: 255 if v > 100 else 0)
        flat = _flatten(frame, alpha)
        regions = flat.quantize(palette=palette, dither=Image.Dither.NONE).filter(ImageFilter.ModeFilter(3))
        index_map = Image.frombytes("L", regions.size, regions.tobytes())
        _, saturation, value = flat.convert("HSV").split()
        lines = ImageChops.lighter(value.point(ramp(60, 120)), saturation.point(ramp(60, 110)))
        edges = ImageChops.lighter(_boundaries(index_map), _boundaries(alpha))
        gray = ImageChops.darker(lines, ImageChops.invert(edges))
        out.append(Image.merge("RGBA", (gray, gray, gray, frame.getchannel("A"))))
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


def render_asset(name, frames, durations, height):
    frames = [clear_white_background(f) for f in frames]
    box = union_bbox(frames)
    frames = fit_height([f.crop(box) for f in frames], height)
    if name not in KEEP_COLOR:
        frames = ink(frames)
    return merge_still_frames(frames, durations, min_ms=ASSET_MIN_FRAME_MS.get(name, MIN_FRAME_MS))


def build_asset(name, frames, durations):
    frames, durations = render_asset(name, frames, durations, ASSET_HEIGHTS[name] * SCALE)
    path = ASSETS / f"{name}.png"
    save_apng(frames, durations, path)
    w, h = frames[0].size
    print(f"  {name}: {len(frames)} frames, {w // SCALE}x{h // SCALE} css px, {path.stat().st_size // 1024} KB")
    return frames, durations


def build_showcase(name, frames, durations):
    """README preview on paper, so the black ink shows on GitHub's dark mode too."""
    height = SHOWCASE_HEIGHTS.get(name, SHOWCASE_HEIGHT)
    frames, durations = render_asset(name, frames, durations, height)
    pad = 16
    w, h = frames[0].size
    canvas_size = (w + 2 * pad, SHOWCASE_HEIGHTS.get(name, SHOWCASE_HEIGHT) + 2 * pad)
    tiles = []
    for frame in frames:
        tile = Image.new("RGBA", canvas_size, PAPER)
        tile.alpha_composite(frame, (pad, pad))
        tiles.append(tile.convert("RGB"))
    save_apng(tiles, durations, SHOWCASE / f"{name}.png")


def build_header(source_frames, durations):
    sprites = {
        "left": [clear_white_background(f.crop(TYPING_BOX)) for f in source_frames],
        "right": [clear_white_background(f.crop(CART_BOX)) for f in source_frames],
    }
    sprites["left"] = ink(fit_height(sprites["left"], 38))
    sprites["right"] = fit_height(sprites["right"], 30)
    if "woodstock-cart" not in KEEP_COLOR:
        sprites["right"] = ink(sprites["right"])
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

    sources = {
        "snoopy-typing": ([f.crop(TYPING_BOX) for f in source_frames], source_durations),
        "woodstock-cart": ([f.crop(CART_BOX) for f in source_frames], source_durations),
    }
    for name in ("snoopy-sleeping", "snoopy-dance", "woodstock-flying", "doghouse-scene"):
        sources[name] = load_frames(GIPHY / f"{name}.gif")

    print("userChrome assets:")
    for name, (frames, durations) in sources.items():
        build_asset(name, frames, durations)

    for name, (frames, durations) in sources.items():
        build_showcase(name, frames, durations)
    print(f"showcase: {len(sources)} previews in {SHOWCASE.relative_to(ROOT)}")

    xpi = package(THEME_DIR, DIST)
    print(f"packaged {xpi.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
