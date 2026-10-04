"""Build the Snoopy theme and userChrome assets, and package the theme as an .xpi."""

import argparse
import io
import shutil
import subprocess
import sys
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
    "snoopy-reading": 24,
    "doghouse-scene": 83,
    "snoopy-dozing": 83,
    "joe-cool": 35,
    "skate-ollie": 30,
    "skate-jump": 30,
    "skate-cruise": 30,
}

# README showcase renders, in px.
SHOWCASE = ROOT / "docs" / "showcase"
SHOWCASE_HEIGHT = 120
SHOWCASE_HEIGHTS = {"woodstock-cart": 90, "doghouse-scene": 160, "snoopy-dozing": 160}
PAPER = (251, 245, 230, 255)

# Assets kept in their original colors instead of black-and-white line art.
KEEP_COLOR = {"woodstock-cart"}

# Always-visible animations get a lower frame rate.
ASSET_MIN_FRAME_MS = {
    "doghouse-scene": 80,
    "snoopy-dozing": 160,
    "skate-ollie": 80,
    "skate-jump": 80,
    "skate-cruise": 80,
}
STABILIZE = {"snoopy-dozing"}
# Joe Cool cropped out of his Listening Lounge badge, above the animated lettering.
JOE_BOX = (130, 40, 350, 282)
# He only wobbles (hand-drawn line boil), so a few slow frames carry it.
JOE_STEP, JOE_FRAME_MS = 13, 250
# Skateboard loops travel across their canvas; userChrome moves them instead.
IN_PLACE = {"skate-ollie", "skate-jump", "skate-cruise"}
# Ollie and cruise ride right then back left; keep the leftward half, the way Snoopy faces.
FRAME_SLICE = {"skate-ollie": slice(60, None), "skate-cruise": slice(60, None)}
# Already black-and-white line art; ink() would turn its gray shading into speckles.
LINE_ART = {"joe-cool"}

# Variants selected by the snoopy.animations.* prefs in userChrome.css.
SLOW_FACTOR = 2
VARIANT_DIRS = {"normal": ASSETS, "slow": ASSETS / "slow", "still": ASSETS / "still"}

# Size budgets checked by `build.py --check` (KB).
BUDGET_ASSET_KB = 120
BUDGET_ASSETS_TOTAL_KB = 900
BUDGET_XPI_KB = 100


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


def stabilize(frames, threshold=40, radius=4, density=24):
    """Drop scattered single-pixel flicker so each delta frame only covers real motion."""
    out = [frames[0]]
    for frame in frames[1:]:
        prev = out[-1]
        changed = ImageChops.difference(prev, frame).convert("L").point(lambda v: 255 if v > threshold else 0)
        moving = (
            changed.filter(ImageFilter.BoxBlur(radius))
            .point(lambda v: 255 if v > density else 0)
            .filter(ImageFilter.MaxFilter(2 * radius + 1))
        )
        out.append(Image.composite(frame, prev, moving))
    return out


def encode_png(frames, durations, grayscale=False):
    """Encode frames as PNG/APNG bytes, then losslessly recompress with oxipng if available."""
    if grayscale:
        frames = [f.convert("LA") for f in frames]
    buf = io.BytesIO()
    if len(frames) == 1:
        frames[0].save(buf, format="PNG", optimize=True)
    else:
        frames[0].save(
            buf,
            format="PNG",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=0,
            blend=0,
        )
    data = buf.getvalue()
    if shutil.which("oxipng"):
        data = subprocess.run(
            ["oxipng", "--opt", "4", "--strip", "safe", "--quiet", "-"],
            input=data,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
    return data


def render_asset(name, frames, durations, height):
    frames = [clear_white_background(f) for f in frames]
    if name in IN_PLACE:
        frames = in_place(frames)
    box = union_bbox(frames)
    frames = fit_height([f.crop(box) for f in frames], height)
    if name in LINE_ART:
        frames = [Image.merge("RGBA", (*[f.convert("L")] * 3, f.getchannel("A"))) for f in frames]
    elif name not in KEEP_COLOR:
        frames = ink(frames)
    if name in STABILIZE:
        frames = stabilize(frames)
    return merge_still_frames(frames, durations, min_ms=ASSET_MIN_FRAME_MS.get(name, MIN_FRAME_MS))


def joe_cool(frames):
    """Drop the badge border and the red lettering, keeping Joe Cool at his turntable."""
    out = []
    for f in frames:
        f = f.convert("RGBA")
        r, g, b, a = f.split()
        inside = a.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(25))
        red = Image.merge("RGB", (r, g, b)).convert("HSV").getchannel("S").point(lambda v: 255 if v > 120 else 0)
        f = Image.composite(Image.new("RGBA", f.size, (255, 255, 255, 255)), f, red)
        f.putalpha(ImageChops.multiply(f.getchannel("A"), inside))
        out.append(f.crop(JOE_BOX))
    return out


def in_place(frames):
    """Re-center each frame horizontally so the sprite animates without traveling."""
    boxes = [f.getchannel("A").getbbox() or (0, 0, 1, 1) for f in frames]
    width = max(b[2] - b[0] for b in boxes)
    out = []
    for f, (x0, _, x1, _) in zip(frames, boxes):
        canvas = Image.new("RGBA", (width, f.height), (0, 0, 0, 0))
        canvas.paste(f.crop((x0, 0, x1, f.height)), ((width - (x1 - x0)) // 2, 0))
        out.append(canvas)
    return out


def asset_outputs(name, frames, durations):
    """Every file written for one userChrome asset, as {path: (frames, durations, grayscale)}."""
    frames, durations = render_asset(name, frames, durations, ASSET_HEIGHTS[name] * SCALE)
    gray = name not in KEEP_COLOR
    return {
        VARIANT_DIRS["normal"] / f"{name}.png": (frames, durations, gray),
        VARIANT_DIRS["slow"] / f"{name}.png": (frames, [d * SLOW_FACTOR for d in durations], gray),
        VARIANT_DIRS["still"] / f"{name}.png": (frames[:1], durations[:1], gray),
    }


def showcase_output(name, frames, durations):
    """README preview on paper, so the black ink shows on GitHub's dark mode too."""
    height = SHOWCASE_HEIGHTS.get(name, SHOWCASE_HEIGHT)
    frames, durations = render_asset(name, frames, durations, height)
    pad = 16
    w, h = frames[0].size
    tiles = []
    for frame in frames:
        tile = Image.new("RGBA", (w + 2 * pad, height + 2 * pad), PAPER)
        tile.alpha_composite(frame, (pad, pad))
        tiles.append(tile.convert("RGB"))
    return {SHOWCASE / f"{name}.png": (tiles, durations, False)}


def header_output(source_frames, durations):
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
    return {HEADER_OUT: (frames, durations, False)}


def all_outputs():
    source_frames, source_durations = load_frames(SOURCE)
    sources = {
        "snoopy-typing": ([f.crop(TYPING_BOX) for f in source_frames], source_durations),
        "woodstock-cart": ([f.crop(CART_BOX) for f in source_frames], source_durations),
    }
    for name in ("snoopy-sleeping", "snoopy-dance", "snoopy-reading", "doghouse-scene", "snoopy-dozing"):
        sources[name] = load_frames(GIPHY / f"{name}.gif")
    joe_frames, joe_durations = load_frames(GIPHY / "joe-cool.gif")
    joe_frames = joe_cool(joe_frames[::JOE_STEP])
    sources["joe-cool"] = (joe_frames, [JOE_FRAME_MS] * len(joe_frames))
    for name in sorted(IN_PLACE):
        frames, durations = load_frames(GIPHY / f"{name}.gif")
        part = FRAME_SLICE.get(name, slice(None))
        sources[name] = (frames[part], durations[part])

    outputs = header_output(source_frames, source_durations)
    for name, (frames, durations) in sources.items():
        outputs.update(asset_outputs(name, frames, durations))
        outputs.update(showcase_output(name, frames, durations))
    return outputs


def package(theme_dir, dist):
    dist.mkdir(exist_ok=True)
    xpi = dist / "snoopy-vertical.xpi"
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(theme_dir.rglob("*")):
            if f.is_file() and f.name != ".DS_Store":
                zf.write(f, f.relative_to(theme_dir))
    return xpi


def frames_match(path, frames, durations):
    if not path.exists():
        return False
    got, got_durations = load_frames(path)
    if len(got) != len(frames) or got_durations[: len(durations)] != durations[: len(got_durations)]:
        return False
    return all(ImageChops.difference(a, b.convert("RGBA")).getbbox(alpha_only=False) is None for a, b in zip(got, frames))


def check(outputs):
    """Fail if committed images are stale or over budget. Compares decoded pixels, not bytes."""
    problems = []
    for path, (frames, durations, gray) in outputs.items():
        expected = [f.convert("LA").convert("RGBA") for f in frames] if gray else frames
        if not frames_match(path, expected, durations if len(frames) > 1 else durations[:0]):
            problems.append(f"stale: {path.relative_to(ROOT)} (run build.py and commit)")

    assets = [p for p in ASSETS.rglob("*.png")]
    for p in assets:
        if p.stat().st_size > BUDGET_ASSET_KB * 1024:
            problems.append(f"over budget: {p.relative_to(ROOT)} is {p.stat().st_size // 1024} KB (max {BUDGET_ASSET_KB} KB)")
    total = sum(p.stat().st_size for p in assets)
    if total > BUDGET_ASSETS_TOTAL_KB * 1024:
        problems.append(f"over budget: userChrome/assets is {total // 1024} KB (max {BUDGET_ASSETS_TOTAL_KB} KB)")
    xpi = package(THEME_DIR, DIST)
    if xpi.stat().st_size > BUDGET_XPI_KB * 1024:
        problems.append(f"over budget: theme .xpi is {xpi.stat().st_size // 1024} KB (max {BUDGET_XPI_KB} KB)")

    for line in problems:
        print(line)
    print(f"checked {len(outputs)} images; assets {total // 1024} KB, xpi {xpi.stat().st_size // 1024} KB")
    return not problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify committed images are current and within budget")
    args = parser.parse_args()

    outputs = all_outputs()
    if args.check:
        sys.exit(0 if check(outputs) else 1)

    for path, (frames, durations, gray) in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode_png(frames, durations, gray))
    for name in ASSET_HEIGHTS:
        p = ASSETS / f"{name}.png"
        print(f"  {p.relative_to(ROOT)}: {p.stat().st_size // 1024} KB")
    xpi = package(THEME_DIR, DIST)
    total = sum(p.stat().st_size for p in ASSETS.rglob("*.png"))
    print(f"wrote {len(outputs)} images (userChrome assets {total // 1024} KB); packaged {xpi.relative_to(ROOT)} ({xpi.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
