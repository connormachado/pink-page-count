"""Generates AppIcon.icns for the Desktop launcher. Stdlib only (struct + zlib)
-- no new dependency, so the icon can be regenerated any time the --pink-hot /
--pink-surface / --ink tokens in web/src/tokens.css ever change (DECISIONS.md
9.1, 15.7).

Run from the repo root:

    .venv/bin/python scripts/make_icon.py

Requires `iconutil` (built into macOS) to assemble the final .icns.

The icon is a pink-hot rounded square with a pink-surface inset (the Phase 2
look, unchanged) carrying a solid scales-of-justice mark in --ink. The mark is
drawn as one filled silhouette, designed to survive 32px in the Dock first and
scaled up from there -- see DECISIONS.md 15.7 before "improving" it. Its whole
shape is parameterized in MARK below so the geometry can be nudged without
redrawing anything.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# DECISIONS.md 9.1 -- the frozen tokens, and the only three hex literals here.
PINK_HOT = (0xFF, 0x2E, 0x88)
PINK_SURFACE = (0xFF, 0xE8, 0xF0)
INK = (0x2B, 0x1A, 0x22)  # --ink: all primary text; here, the scales mark (15.7)

# The sizes iconutil expects in an .iconset, by output filename.
ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}

# --- The scales mark -----------------------------------------------------------
#
# Every value is a fraction of the icon's edge length, measured from the centre,
# with y growing downward. The mark's bounding box is roughly +/-0.25 wide and
# +/-0.19 tall, so it clears both the pink-surface inset (+/-0.32) and the
# icon's rounded corner (DECISIONS.md 15.7's "generous margin").
#
# The failure mode this geometry is chosen against: at 32px the beam and the two
# pan stems drop toward one pixel and vanish, leaving two floating pans over a
# post. So the beam is a thick capsule (not a line), the pans hang on short fat
# stems, and the base is a solid triangle + foot bar rather than an outline --
# a blunt shape that still reads when every feature is 1-2px wide.
MARK = {
    "offset_y": -0.010,   # nudge the whole mark up so it sits optically centred
    "beam_half_w": 0.170, # half the beam length (also the pan spacing)
    "beam_r": 0.034,      # beam half-thickness -- the number that must survive 32px
    "top_y": -0.150,      # beam centreline
    "post_r": 0.027,      # central column half-width
    "base_y": 0.175,      # underside of the foot
    "base_half_w": 0.100, # half the foot width
    "base_h": 0.155,      # foot triangle height (apex reaches up toward centre)
    "foot_r": 0.029,      # foot bar half-thickness -- keeps the base crisp small
    "pan_drop": 0.150,    # beam end -> pan centre (pan hangs clear of the beam)
    "stem_r": 0.020,      # pan stem half-width
    "pan_r": 0.076,       # pan radius -- a solid round weight, the robust form
}


def _rounded_box_sdf(x: float, y: float, half_w: float, half_h: float, radius: float) -> float:
    """Signed distance from (x, y) to a rounded box centered at the origin.
    Negative inside, positive outside, zero on the edge -- the standard
    rounded-rect SDF. Cheap enough to do once per pixel with no supersampling."""
    qx = abs(x) - (half_w - radius)
    qy = abs(y) - (half_h - radius)
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    return outside + min(max(qx, qy), 0.0) - radius


def _segment_sdf(
    px: float, py: float, ax: float, ay: float, bx: float, by: float, r: float
) -> float:
    """Signed distance to a capsule: the segment a->b thickened by r. Used for
    the beam, the post, the pan stems and the foot bar -- every straight member
    of the mark, so each one has rounded ends and a genuine solid width."""
    pax, pay = px - ax, py - ay
    bax, bay = bx - ax, by - ay
    denom = bax * bax + bay * bay
    h = 0.0 if denom == 0.0 else min(1.0, max(0.0, (pax * bax + pay * bay) / denom))
    dx, dy = pax - bax * h, pay - bay * h
    return (dx * dx + dy * dy) ** 0.5 - r


def _disc_sdf(px: float, py: float, cx: float, cy: float, r: float) -> float:
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 - r


def _triangle_sdf(px, py, a, b, c) -> float:
    """Signed distance to the solid triangle a-b-c (Inigo Quilez's formula).
    Winding-independent: negative inside either way. This is the foot's stand."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    e0x, e0y = bx - ax, by - ay
    e1x, e1y = cx - bx, cy - by
    e2x, e2y = ax - cx, ay - cy
    v0x, v0y = px - ax, py - ay
    v1x, v1y = px - bx, py - by
    v2x, v2y = px - cx, py - cy

    def _leg(vx, vy, ex, ey):
        t = min(1.0, max(0.0, (vx * ex + vy * ey) / (ex * ex + ey * ey)))
        dx, dy = vx - ex * t, vy - ey * t
        return dx * dx + dy * dy

    d_dist = min(
        _leg(v0x, v0y, e0x, e0y),
        _leg(v1x, v1y, e1x, e1y),
        _leg(v2x, v2y, e2x, e2y),
    )
    s = 1.0 if (e0x * e2y - e0y * e2x) > 0.0 else -1.0
    d_side = min(
        s * (v0x * e0y - v0y * e0x),
        s * (v1x * e1y - v1y * e1x),
        s * (v2x * e2y - v2y * e2x),
    )
    return -(d_dist ** 0.5) * (1.0 if d_side > 0.0 else -1.0)


def _mark_sdf(x: float, y: float, size: float) -> float:
    """Signed distance to the whole scales silhouette (union = min of parts),
    in pixels, for an icon `size` px on a side. Everything scales with `size`,
    so the shape is identical at every export size."""
    m = MARK
    oy = m["offset_y"] * size
    bx = m["beam_half_w"] * size
    ty = m["top_y"] * size + oy
    by_ = m["base_y"] * size + oy

    # beam
    d = _segment_sdf(x, y, -bx, ty, bx, ty, m["beam_r"] * size)
    # central post
    d = min(d, _segment_sdf(x, y, 0.0, ty, 0.0, by_, m["post_r"] * size))
    # foot: solid triangle flaring from a point near centre down to the foot...
    d = min(
        d,
        _triangle_sdf(
            x, y,
            (-m["base_half_w"] * size, by_),
            (m["base_half_w"] * size, by_),
            (0.0, by_ - m["base_h"] * size),
        ),
    )
    # ...capped by a bar so the bottom edge stays crisp when it is only 1-2px
    d = min(
        d,
        _segment_sdf(
            x, y,
            -m["base_half_w"] * size, by_,
            m["base_half_w"] * size, by_,
            m["foot_r"] * size,
        ),
    )
    # the two pans: a short fat stem, then a solid round weight hanging from
    # each beam end. A full disc (not a shallow bowl) is what still reads as a
    # balance when it is only a few pixels across -- DECISIONS.md 15.7.
    pcy = ty + m["pan_drop"] * size
    for sx in (-bx, bx):
        d = min(d, _segment_sdf(x, y, sx, ty, sx, pcy, m["stem_r"] * size))
        d = min(d, _disc_sdf(x, y, sx, pcy, m["pan_r"] * size))
    return d


def _coverage(distance: float) -> float:
    """~1px antialiased band around an SDF's zero crossing, clamped to [0, 1]."""
    return max(0.0, min(1.0, 0.5 - distance))


def _mark_coverage(px: int, py: int, cx: float, cy: float, size: int, ss: int) -> float:
    """Ink coverage of the mark at pixel (px, py). At small export sizes the
    beam and stems are ~1px, where a single sample aliases them away; ss>1
    averages an ss x ss grid of hard inside/outside tests instead."""
    if ss == 1:
        return _coverage(_mark_sdf(px + 0.5 - cx, py + 0.5 - cy, size))
    hits = 0
    step = 1.0 / ss
    for iy in range(ss):
        yy = py + (iy + 0.5) * step - cy
        for ix in range(ss):
            xx = px + (ix + 0.5) * step - cx
            if _mark_sdf(xx, yy, size) <= 0.0:
                hits += 1
    return hits / (ss * ss)


def _render(size: int) -> bytes:
    """RGBA pixel bytes for one icon size: a pink-hot rounded square with a
    pink-surface inset (both frozen tokens) on a transparent background, with
    the --ink scales mark composited over the inset."""
    cx = cy = size / 2.0

    outer_half = size * 0.44
    outer_radius = outer_half * 0.42
    inner_half = size * 0.32
    inner_radius = inner_half * 0.42

    # Supersample the mark only where its thin members would otherwise vanish.
    if size <= 128:
        ss = 4
    elif size <= 256:
        ss = 2
    else:
        ss = 1

    pixels = bytearray(size * size * 4)
    for py in range(size):
        y = py + 0.5 - cy
        for px in range(size):
            x = px + 0.5 - cx

            outer_d = _rounded_box_sdf(x, y, outer_half, outer_half, outer_radius)
            alpha = _coverage(outer_d)
            offset = (py * size + px) * 4
            if alpha <= 0.0:
                continue

            inner_d = _rounded_box_sdf(x, y, inner_half, inner_half, inner_radius)
            inner_t = _coverage(inner_d)
            r = PINK_HOT[0] + (PINK_SURFACE[0] - PINK_HOT[0]) * inner_t
            g = PINK_HOT[1] + (PINK_SURFACE[1] - PINK_HOT[1]) * inner_t
            b = PINK_HOT[2] + (PINK_SURFACE[2] - PINK_HOT[2]) * inner_t

            mark_t = _mark_coverage(px, py, cx, cy, size, ss)
            if mark_t > 0.0:
                r += (INK[0] - r) * mark_t
                g += (INK[1] - g) * mark_t
                b += (INK[2] - b) * mark_t

            pixels[offset] = int(r)
            pixels[offset + 1] = int(g)
            pixels[offset + 2] = int(b)
            pixels[offset + 3] = int(alpha * 255)

    return bytes(pixels)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _write_png(path: Path, size: int, rgba: bytes) -> None:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = bytearray()
    stride = size * 4
    for row in range(size):
        raw.append(0)  # filter type: none
        raw.extend(rgba[row * stride : (row + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)

    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", idat)
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _write_previews(rendered: dict[int, bytes]) -> None:
    """Drop a PNG per size into scripts/icon-preview/ so a render can be looked
    at, not reasoned about (DECISIONS.md 15.7). Rewritten on every run."""
    out = REPO_ROOT / "scripts" / "icon-preview"
    out.mkdir(parents=True, exist_ok=True)
    for size in sorted(rendered):
        _write_png(out / f"icon_{size:04d}.png", size, rendered[size])
    print(f"Previews: {out}")


def main() -> None:
    if shutil.which("iconutil") is None:
        sys.exit("iconutil not found -- this script only runs on macOS.")

    preview_only = "--previews-only" in sys.argv[1:]
    preview_sizes = {16, 32, 64, 128, 256, 512, 1024}

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()

        rendered: dict[int, bytes] = {}
        sizes = preview_sizes if preview_only else set(ICONSET_SIZES.values()) | preview_sizes
        for size in sorted(sizes):
            rendered[size] = _render(size)

        _write_previews({s: rendered[s] for s in preview_sizes})
        if preview_only:
            return

        for filename, size in ICONSET_SIZES.items():
            _write_png(iconset / filename, size, rendered[size])

        output = REPO_ROOT / "AppIcon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(output)],
            check=True,
        )
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
