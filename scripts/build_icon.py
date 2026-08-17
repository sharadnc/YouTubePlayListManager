"""
PURPOSE:
    Generate a modern upscale blue-themed multi-size ytpm.ico for the GUI.

INTERNAL LOGIC:
    Draws a 512px master (gradient rounded square, playlist bars, chevron),
    then saves ICO with sizes 16–256 via Pillow.

EXAMPLE INVOCATION:
    python scripts/build_icon.py
    # Expected: assets/ytpm.ico created
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "ytpm.ico"
SIZES: List[int] = [16, 32, 48, 64, 128, 256]


def _lerp(a: int, b: int, t: float) -> int:
    """
    PURPOSE:
        Linearly interpolate two channel values.

    INTERNAL LOGIC:
        Round a + (b-a)*t.

    EXAMPLE INVOCATION:
        _lerp(0, 255, 0.5)  # 128
    """
    return int(round(a + (b - a) * t))


def _gradient_color(y: int, h: int) -> Tuple[int, int, int]:
    """
    PURPOSE:
        Map vertical position to deep→royal blue RGB.

    INTERNAL LOGIC:
        Interpolates #0B1F3A → #1F538D → #3498DB.

    EXAMPLE INVOCATION:
        _gradient_color(0, 512)
    """
    t = y / max(h - 1, 1)
    c0 = (11, 31, 58)
    c1 = (31, 83, 141)
    c2 = (52, 152, 219)
    if t < 0.55:
        u = t / 0.55
        return (_lerp(c0[0], c1[0], u), _lerp(c0[1], c1[1], u), _lerp(c0[2], c1[2], u))
    u = (t - 0.55) / 0.45
    return (_lerp(c1[0], c2[0], u), _lerp(c1[1], c2[1], u), _lerp(c1[2], c2[2], u))


def draw_master(size: int = 512) -> Image.Image:
    """
    PURPOSE:
        Render the high-resolution app icon artwork.

    INTERNAL LOGIC:
        Rounded gradient tile, soft highlight, three list bars, play chevron.

    EXAMPLE INVOCATION:
        img = draw_master(512)
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Rounded rectangle mask
    radius = int(size * 0.18)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    # Gradient fill
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        r, g, b = _gradient_color(y, size)
        for x in range(size):
            px[x, y] = (r, g, b, 255)
    img = Image.composite(grad, img, mask)
    draw = ImageDraw.Draw(img)

    # Soft top highlight
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.ellipse(
        (-size * 0.2, -size * 0.45, size * 1.2, size * 0.55),
        fill=(255, 255, 255, 38),
    )
    img = Image.alpha_composite(img, highlight)
    draw = ImageDraw.Draw(img)

    # Playlist bars (left)
    margin_x = int(size * 0.18)
    bar_w = int(size * 0.42)
    bar_h = int(size * 0.08)
    gap = int(size * 0.07)
    start_y = int(size * 0.28)
    for i in range(3):
        y0 = start_y + i * (bar_h + gap)
        x0 = margin_x
        # Dot / bullet
        r = bar_h // 2
        cx, cy = x0 + r, y0 + r
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(230, 242, 255, 255))
        # Bar
        bx0 = x0 + bar_h + int(size * 0.04)
        draw.rounded_rectangle(
            (bx0, y0, bx0 + bar_w, y0 + bar_h),
            radius=bar_h // 2,
            fill=(220, 235, 255, 230),
        )

    # Play chevron (right) — geometric triangle, not YouTube logo
    cx = int(size * 0.72)
    cy = int(size * 0.50)
    scale = size * 0.16
    tri = [
        (cx - scale * 0.35, cy - scale),
        (cx - scale * 0.35, cy + scale),
        (cx + scale * 0.85, cy),
    ]
    draw.polygon(tri, fill=(255, 255, 255, 245))
    # Subtle ring behind chevron
    ring_r = int(size * 0.20)
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline=(255, 255, 255, 70),
        width=max(2, size // 64),
    )
    img = Image.alpha_composite(img, overlay)
    return img


def build_ico(dest: Path = OUT) -> Path:
    """
    PURPOSE:
        Write multi-resolution ytpm.ico from the master artwork.

    INTERNAL LOGIC:
        Resamples master to each size; saves as ICO.

    EXAMPLE INVOCATION:
        build_ico()
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    master = draw_master(512)
    images = [master.resize((s, s), Image.Resampling.LANCZOS) for s in SIZES]
    images[0].save(
        dest,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )
    # Pillow ICO save sometimes needs all frames via primary save differently:
    master.save(dest, format="ICO", sizes=[(s, s) for s in SIZES])
    return dest


def main() -> None:
    """
    PURPOSE:
        CLI entry to regenerate assets/ytpm.ico.

    INTERNAL LOGIC:
        Calls build_ico and prints path.

    EXAMPLE INVOCATION:
        python scripts/build_icon.py
    """
    path = build_ico()
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
