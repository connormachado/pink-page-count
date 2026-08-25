"""Generates AppIcon.icns for the Desktop launcher. Stdlib only (struct + zlib)
-- no new dependency, so the icon can be regenerated any time the --pink-hot /
--pink-surface tokens in web/src/tokens.css ever change (DECISIONS.md 9.1).

Run from the repo root:

    .venv/bin/python scripts/make_icon.py

Requires `iconutil` (built into macOS) to assemble the final .icns.
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

# DECISIONS.md 9.1 -- the frozen tokens, and the only two hex literals here.
PINK_HOT = (0xFF, 0x2E, 0x88)
PINK_SURFACE = (0xFF, 0xE8, 0xF0)

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


def _rounded_box_sdf(x: float, y: float, half_w: float, half_h: float, radius: float) -> float:
    """Signed distance from (x, y) to a rounded box centered at the origin.
    Negative inside, positive outside, zero on the edge -- the standard
    rounded-rect SDF. Cheap enough to do once per pixel with no supersampling."""
    qx = abs(x) - (half_w - radius)
    qy = abs(y) - (half_h - radius)
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    return outside + min(max(qx, qy), 0.0) - radius


def _coverage(distance: float) -> float:
    """~1px antialiased band around an SDF's zero crossing, clamped to [0, 1]."""
    return max(0.0, min(1.0, 0.5 - distance))


def _render(size: int) -> bytes:
    """RGBA pixel bytes for one icon size: a pink-hot rounded square with a
    pink-surface inset, both frozen tokens, on a transparent background."""
    cx = cy = size / 2.0

    outer_half = size * 0.44
    outer_radius = outer_half * 0.42
    inner_half = size * 0.32
    inner_radius = inner_half * 0.42

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


def main() -> None:
    if shutil.which("iconutil") is None:
        sys.exit("iconutil not found -- this script only runs on macOS.")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()

        rendered: dict[int, bytes] = {}
        for filename, size in ICONSET_SIZES.items():
            if size not in rendered:
                rendered[size] = _render(size)
            _write_png(iconset / filename, size, rendered[size])

        output = REPO_ROOT / "AppIcon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(output)],
            check=True,
        )
        print(f"Wrote {output}")


if __name__ == "__main__":
    main()
