"""Build the Snoopy theme header image and package the theme as an .xpi."""

import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
SOURCE = ROOT / "source" / "original-header.png"
THEME_DIR = ROOT / "theme"
HEADER_OUT = THEME_DIR / "images" / "header.png"
DIST = ROOT / "dist"

# Visible header height with vertical tabs (nav bar only) on macOS.
HEADER_HEIGHT = 40

# Distance in px from the window center to the inner edge of each sprite.
# Increase these if the sprites overlap the URL bar.
LEFT_GAP = 430
RIGHT_GAP = 430

# Regions of the original 2090x70 animation, as (left, top, right, bottom).
SPRITES = {
    "snoopy": {
        "box": (1840, 0, 1962, 70),
        "height": 38,
        "side": "left",
        "flip": False,
    },
    "woodstock_cart": {
        "box": (626, 4, 674, 42),
        "height": 30,
        "side": "right",
        "flip": False,
    },
}


def load_frames(path):
    im = Image.open(path)
    frames, durations = [], []
    for i in range(im.n_frames):
        im.seek(i)
        frames.append(im.convert("RGBA"))
        durations.append(im.info.get("duration", 66))
    return frames, durations


def render_sprite(frame, spec):
    sprite = frame.crop(spec["box"])
    scale = spec["height"] / sprite.height
    if scale != 1:
        size = (round(sprite.width * scale), spec["height"])
        sprite = sprite.resize(size, Image.LANCZOS)
    if spec["flip"]:
        sprite = sprite.transpose(Image.FLIP_LEFT_RIGHT)
    return sprite


def build_frames(frames):
    sample = {name: render_sprite(frames[0], spec) for name, spec in SPRITES.items()}
    half = max(
        (LEFT_GAP if spec["side"] == "left" else RIGHT_GAP) + sample[name].width
        for name, spec in SPRITES.items()
    )
    width = half * 2

    out = []
    for frame in frames:
        canvas = Image.new("RGBA", (width, HEADER_HEIGHT), (0, 0, 0, 0))
        for spec in SPRITES.values():
            sprite = render_sprite(frame, spec)
            if spec["side"] == "left":
                x = half - LEFT_GAP - sprite.width
            else:
                x = half + RIGHT_GAP
            y = (HEADER_HEIGHT - sprite.height) // 2
            canvas.paste(sprite, (x, y))
        out.append(canvas)
    return out


def save_apng(frames, durations, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=1,
        blend=0,
    )


def package(theme_dir, dist):
    dist.mkdir(exist_ok=True)
    xpi = dist / "snoopy-vertical.xpi"
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(theme_dir.rglob("*")):
            if f.is_file() and f.name != ".DS_Store":
                zf.write(f, f.relative_to(theme_dir))
    return xpi


def main():
    frames, durations = load_frames(SOURCE)
    header = build_frames(frames)
    save_apng(header, durations, HEADER_OUT)
    xpi = package(THEME_DIR, DIST)
    print(f"{len(header)} frames, {header[0].width}x{header[0].height} -> {HEADER_OUT.relative_to(ROOT)}")
    print(f"packaged {xpi.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
