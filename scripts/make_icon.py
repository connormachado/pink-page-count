"""Generates AppIcon.icns for the Desktop launcher. Stdlib only (struct + zlib
+ math) -- no new dependency, so the icon can be regenerated any time its
geometry or its two colours change (DECISIONS.md 15.7). Those colours are the
icon's own and no longer mirror web/src/tokens.css: a token change does not
oblige a re-run any more (15.7.4, 15.7.5).

Run from the repo root:

    .venv/bin/python scripts/make_icon.py

Requires `iconutil` (built into macOS) to assemble the final .icns.

The icon is one flat ICON_BG rounded square -- no inset, one colour edge to
edge (15.7.4) -- carrying a scales-of-justice mark in pure black (15.7.5). The
rounded square's size and corner radius are the Phase 2 ones, unchanged; only
the two fills changed. The mark is the drawing in `scales-mark.svg` at the root,
rasterized here rather than parsed -- there is no SVG library in this project
and there is not going to be one. Its whole geometry is parameterized in MARK
below, in the SVG's own 100x100 units, so every number can be read straight off
that file and nudged without redrawing anything.

Read DECISIONS.md 15.7 before changing the mark. In particular: the four chains
are 3 units wide in a 100-unit space and go sub-pixel below 64px. That is
recorded there as accepted, not as a defect to fix by thickening them.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two hex literals here. Neither is a token any more, and neither tracks
# tokens.css -- the icon has its own two colours, for the reasons in 15.7.4
# (the plate) and 15.7.5 (the mark). Do not "restore" either to a token value.
ICON_BG = (0xED, 0xB8, 0xCE)  # the one colour the whole plate is, edge to edge
MARK_INK = (0x00, 0x00, 0x00)  # the scales mark: pure black, not --ink (15.7.5)

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
# Geometry is kept in `scales-mark.svg`'s own coordinate space: a 100x100 box,
# origin top-left, y growing downward, the mark centred on (50, 50). Keeping the
# SVG's numbers means the two files can be diffed by eye.
#
# Two scalars place that box on the icon:
#
#   svg_inset  the scale(0.78) the SVG itself applies about (50, 50)
#   fit        what fraction of the icon's edge the 100-unit box then spans
#
# Their product is the only thing that decides how big the mark is. `fit` is set
# so the mark's half-width lands at 0.246 of the edge -- the same half-width the
# previous mark had, so the clearance to the icon's rounded corner is unchanged.
# It used to also be sized against a +/-0.32 pink-surface inset; that inset is
# gone (15.7.4) and the number was kept anyway, so the mark is untouched.
MARK = {
    # placement -----------------------------------------------------------------
    "svg_inset": 0.78,
    "fit": 0.75,
    "offset_y": -0.003,   # optical nudge, fraction of the edge; negative is up.
                          # The mark's own bbox centre sits 0.5 units low in the
                          # SVG, and this takes that back out.

    "cx": 50.0,           # the SVG's centre line; everything mirrors about it

    # teardrop finial: a cusp at the top over a round belly ----------------------
    "finial_tip_y": 11.0,
    "finial_cy": 22.0,
    "finial_r": 6.0,
    "finial_c1": (53.5, 17.0),  # cubic controls for the right flank; the left
    "finial_c2": (56.0, 19.5),  # flank is their mirror, reversed

    # vertical post -------------------------------------------------------------
    "post_top_y": 20.0,   # buried inside the finial
    "post_bottom_y": 76.0,  # buried inside the plinth
    "post_w": 6.0,

    # arced beam: a quadratic bowing up between its two ends ---------------------
    "beam_half_w": 26.0,  # ends land at x = 24 and x = 76
    "beam_y": 33.0,
    "beam_rise": 9.0,     # control point at (50, 24)
    "beam_w": 4.5,        # round caps, per the SVG's stroke-linecap
    "beam_steps": 16,     # capsules the quadratic is flattened into
    "knob_r": 4.0,        # solid knob at each beam end

    # chains: two per side, beam end down to the pan's rim -----------------------
    "chain_spread": 15.0,  # horizontal reach from the beam end to each rim
    "chain_w": 3.0,        # sub-pixel below 64px, on purpose -- 15.7

    # pans: a filled semicircle hanging below its chord --------------------------
    "pan_cy": 54.0,
    "pan_r": 16.0,         # chord runs the full diameter, so the pans meet the
                           # chain feet exactly at their rims

    # plinth: a trapezoid flaring down off the post ------------------------------
    "plinth_top_half_w": 10.0,
    "plinth_top_y": 74.0,
    "plinth_bottom_half_w": 16.0,
    "plinth_bottom_y": 84.0,

    # foot bar ------------------------------------------------------------------
    "foot_half_w": 23.0,
    "foot_top_y": 84.0,
    "foot_h": 6.0,         # rx == h/2 in the SVG, so it is exactly a capsule
}


# --- Signed-distance primitives -------------------------------------------------
#
# Each factory closes over its geometry and returns an SDF over the SVG's
# coordinate space: negative inside, positive outside, magnitude in SVG units.
# The mark is the union of all of them, and a union is a min.


def _rounded_box_sdf(x: float, y: float, half_w: float, half_h: float, radius: float) -> float:
    """Signed distance from (x, y) to a rounded box centered at the origin.
    Negative inside, positive outside, zero on the edge -- the standard
    rounded-rect SDF. Cheap enough to do once per pixel with no supersampling."""
    qx = abs(x) - (half_w - radius)
    qy = abs(y) - (half_h - radius)
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    return outside + min(max(qx, qy), 0.0) - radius


def _capsule(ax: float, ay: float, bx: float, by: float, r: float):
    """The segment a->b thickened by r, with round ends -- SVG's
    `stroke-linecap: round`. The beam and the foot bar."""
    bax, bay = bx - ax, by - ay
    denom = bax * bax + bay * bay

    def sdf(px: float, py: float) -> float:
        pax, pay = px - ax, py - ay
        h = (pax * bax + pay * bay) / denom
        if h < 0.0:
            h = 0.0
        elif h > 1.0:
            h = 1.0
        dx, dy = pax - bax * h, pay - bay * h
        return (dx * dx + dy * dy) ** 0.5 - r

    return sdf


def _obox(ax: float, ay: float, bx: float, by: float, r: float):
    """The segment a->b thickened by r, with flat ends -- SVG's *default*
    `stroke-linecap: butt`, which is what `<line>` uses. The post and the four
    chains: their ends are buried in other parts, and a round cap on a chain
    would bulge past the pan's rim."""
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    dx, dy = bx - ax, by - ay
    length = (dx * dx + dy * dy) ** 0.5
    half_l = length / 2.0
    ux, uy = dx / length, dy / length

    def sdf(px: float, py: float) -> float:
        wx, wy = px - mx, py - my
        qx = abs(wx * ux + wy * uy) - half_l
        qy = abs(wy * ux - wx * uy) - r
        ox = qx if qx > 0.0 else 0.0
        oy = qy if qy > 0.0 else 0.0
        inner = qx if qx > qy else qy
        return (ox * ox + oy * oy) ** 0.5 + (inner if inner < 0.0 else 0.0)

    return sdf


def _disc(dcx: float, dcy: float, r: float):
    """A filled circle. The two beam-end knobs."""

    def sdf(px: float, py: float) -> float:
        dx, dy = px - dcx, py - dcy
        return (dx * dx + dy * dy) ** 0.5 - r

    return sdf


def _pan(dcx: float, dcy: float, r: float):
    """A filled semicircle hanging below its chord: the disc intersected with
    the half-plane under y = dcy. This is `M x-r,y A r r 0 0 0 x+r,y Z` -- the
    arc sweeps below, and Z draws the chord back."""

    def sdf(px: float, py: float) -> float:
        dx, dy = px - dcx, py - dcy
        d = (dx * dx + dy * dy) ** 0.5 - r
        chord = dcy - py
        return d if d > chord else chord

    return sdf


def _polygon(pts):
    """Signed distance to a closed simple polygon (Inigo Quilez's sdPolygon):
    nearest-edge distance, signed by a crossing count so it works for any
    winding. Used for the two shapes no primitive fits -- the teardrop finial
    (its flanks are cubics, flattened) and the trapezoid plinth."""
    poly = tuple(pts)
    edges = []
    for i in range(len(poly)):
        ix, iy = poly[i]
        jx, jy = poly[i - 1]
        ex, ey = jx - ix, jy - iy
        edges.append((ix, iy, jy, ex, ey, 1.0 / (ex * ex + ey * ey)))
    edges = tuple(edges)

    def sdf(px: float, py: float) -> float:
        d = 1e18
        s = 1.0
        for ix, iy, jy, ex, ey, inv_ee in edges:
            wx, wy = px - ix, py - iy
            t = (wx * ex + wy * ey) * inv_ee
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            bx, by = wx - ex * t, wy - ey * t
            dd = bx * bx + by * by
            if dd < d:
                d = dd
            # Flip the sign on every edge the ray from p crosses.
            if (py >= iy) == (py < jy) == (ex * wy > ey * wx):
                s = -s
        return s * d ** 0.5

    return sdf


def _flatten_cubic(p0, p1, p2, p3, steps: int, skip_first: bool = False):
    """A cubic Bezier as a polyline, endpoints included."""
    out = []
    for i in range(1 if skip_first else 0, steps + 1):
        t = i / steps
        mt = 1.0 - t
        a, b = mt * mt * mt, 3.0 * mt * mt * t
        c, d = 3.0 * mt * t * t, t * t * t
        out.append(
            (
                a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
            )
        )
    return out


def _flatten_quad(p0, p1, p2, steps: int):
    """A quadratic Bezier as a polyline, endpoints included."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        a, b, c = mt * mt, 2.0 * mt * t, t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0],
                    a * p0[1] + b * p1[1] + c * p2[1]))
    return out


# --- Assembling the mark --------------------------------------------------------

_PARTS: tuple | None = None


def _build_parts() -> tuple:
    """The mark as a list of (bounding box, sdf) pairs in SVG units. Built once:
    the geometry is scale-free, so the same list serves every export size.

    Every part carries a box because distance-to-box is a lower bound on
    distance-to-part, which lets `_mark_sdf_svg` skip a part outright once it
    already holds something nearer. Without that the finial's 30-odd polygon
    edges would be evaluated for every pixel of a 1024px render.

    Ordered roughly largest-first so the running minimum drops early and the
    thin parts get culled."""
    m = MARK
    cx = m["cx"]
    parts: list = []

    def add(fn, x0, y0, x1, y1) -> None:
        parts.append(((x0, y0, x1, y1), fn))

    # post -- butt caps; both ends are buried, in the finial and in the plinth
    post_r = m["post_w"] / 2.0
    add(
        _obox(cx, m["post_top_y"], cx, m["post_bottom_y"], post_r),
        cx - post_r, m["post_top_y"], cx + post_r, m["post_bottom_y"],
    )

    # the two pans
    pan_r = m["pan_r"]
    for side in (-1.0, 1.0):
        pcx = cx + side * m["beam_half_w"]
        add(
            _pan(pcx, m["pan_cy"], pan_r),
            pcx - pan_r, m["pan_cy"], pcx + pan_r, m["pan_cy"] + pan_r,
        )

    # plinth
    add(
        _polygon(
            (
                (cx - m["plinth_top_half_w"], m["plinth_top_y"]),
                (cx + m["plinth_top_half_w"], m["plinth_top_y"]),
                (cx + m["plinth_bottom_half_w"], m["plinth_bottom_y"]),
                (cx - m["plinth_bottom_half_w"], m["plinth_bottom_y"]),
            )
        ),
        cx - m["plinth_bottom_half_w"], m["plinth_top_y"],
        cx + m["plinth_bottom_half_w"], m["plinth_bottom_y"],
    )

    # foot bar -- the SVG's rx equals half its height, so it is a capsule
    foot_r = m["foot_h"] / 2.0
    foot_cy = m["foot_top_y"] + foot_r
    foot_x = m["foot_half_w"] - foot_r
    add(
        _capsule(cx - foot_x, foot_cy, cx + foot_x, foot_cy, foot_r),
        cx - m["foot_half_w"], m["foot_top_y"],
        cx + m["foot_half_w"], m["foot_top_y"] + m["foot_h"],
    )

    # beam -- one quadratic, flattened to capsules so the round caps come free
    beam_r = m["beam_w"] / 2.0
    beam_pts = _flatten_quad(
        (cx - m["beam_half_w"], m["beam_y"]),
        (cx, m["beam_y"] - m["beam_rise"]),
        (cx + m["beam_half_w"], m["beam_y"]),
        m["beam_steps"],
    )
    beam_segs = tuple(
        _capsule(a[0], a[1], b[0], b[1], beam_r)
        for a, b in zip(beam_pts, beam_pts[1:])
    )

    def beam_sdf(px: float, py: float, segs=beam_segs) -> float:
        d = 1e18
        for seg in segs:
            v = seg(px, py)
            if v < d:
                d = v
        return d

    add(
        beam_sdf,
        min(p[0] for p in beam_pts) - beam_r, min(p[1] for p in beam_pts) - beam_r,
        max(p[0] for p in beam_pts) + beam_r, max(p[1] for p in beam_pts) + beam_r,
    )

    # beam-end knobs
    knob_r = m["knob_r"]
    for side in (-1.0, 1.0):
        kx = cx + side * m["beam_half_w"]
        add(
            _disc(kx, m["beam_y"], knob_r),
            kx - knob_r, m["beam_y"] - knob_r, kx + knob_r, m["beam_y"] + knob_r,
        )

    # chains -- four of them, each from a beam end to one rim of its pan
    chain_r = m["chain_w"] / 2.0
    for side in (-1.0, 1.0):
        ex = cx + side * m["beam_half_w"]
        for lean in (-1.0, 1.0):
            fx = ex + lean * m["chain_spread"]
            add(
                _obox(ex, m["beam_y"], fx, m["pan_cy"], chain_r),
                min(ex, fx) - chain_r, m["beam_y"] - chain_r,
                max(ex, fx) + chain_r, m["pan_cy"] + chain_r,
            )

    # finial -- right flank (cubic), lower semicircle, left flank (mirrored)
    fr, fcy = m["finial_r"], m["finial_cy"]
    tip = (cx, m["finial_tip_y"])
    c1, c2 = m["finial_c1"], m["finial_c2"]
    finial = _flatten_cubic(tip, c1, c2, (cx + fr, fcy), 12)
    arc_steps = 18
    for i in range(1, arc_steps):
        a = math.pi * i / arc_steps
        finial.append((cx + fr * math.cos(a), fcy + fr * math.sin(a)))
    finial += _flatten_cubic(
        (cx - fr, fcy),
        (2.0 * cx - c2[0], c2[1]),
        (2.0 * cx - c1[0], c1[1]),
        tip,
        12,
    )[:-1]  # drop the repeated tip; the polygon closes itself
    add(
        _polygon(finial),
        min(p[0] for p in finial), m["finial_tip_y"],
        max(p[0] for p in finial), fcy + fr,
    )

    return tuple(parts)


def _parts() -> tuple:
    global _PARTS
    if _PARTS is None:
        _PARTS = _build_parts()
    return _PARTS


def _mark_sdf_svg(u: float, v: float) -> float:
    """Signed distance to the whole mark, in SVG units, at SVG point (u, v).
    The union of every part, which is the minimum over them."""
    best = 1e18
    for (x0, y0, x1, y1), fn in _parts():
        dx = x0 - u
        if dx < 0.0:
            dx = u - x1
            if dx < 0.0:
                dx = 0.0
        dy = y0 - v
        if dy < 0.0:
            dy = v - y1
            if dy < 0.0:
                dy = 0.0
        if (dx > 0.0 or dy > 0.0) and (dx * dx + dy * dy) ** 0.5 >= best:
            continue
        d = fn(u, v)
        if d < best:
            best = d
    return best


def _unit(size: int) -> float:
    """Pixels per SVG unit for an icon `size` px on a side."""
    return MARK["svg_inset"] * MARK["fit"] * size / 100.0


def _mark_bbox_px(size: int) -> tuple[float, float, float, float]:
    """The mark's bounding box in pixels, relative to the icon's centre and
    padded by 1px for the antialiasing band. No pixel outside it carries ink,
    so `_render` can skip the mark entirely for most of the icon."""
    unit = _unit(size)
    oy = MARK["offset_y"] * size
    x0 = min(b[0] for b, _ in _parts())
    y0 = min(b[1] for b, _ in _parts())
    x1 = max(b[2] for b, _ in _parts())
    y1 = max(b[3] for b, _ in _parts())
    return (
        (x0 - 50.0) * unit - 1.0,
        (y0 - 50.0) * unit + oy - 1.0,
        (x1 - 50.0) * unit + 1.0,
        (y1 - 50.0) * unit + oy + 1.0,
    )


def _coverage(distance: float) -> float:
    """~1px antialiased band around an SDF's zero crossing, clamped to [0, 1]."""
    return max(0.0, min(1.0, 0.5 - distance))


def _mark_coverage(px: int, py: int, cx: float, cy: float, size: int, ss: int) -> float:
    """Ink coverage of the mark at pixel (px, py). At small export sizes the
    beam and the chains are ~1px or less, where a single sample aliases them
    away; ss>1 averages an ss x ss grid of hard inside/outside tests instead."""
    unit = _unit(size)
    inv = 1.0 / unit
    oy = MARK["offset_y"] * size
    if ss == 1:
        u = 50.0 + (px + 0.5 - cx) * inv
        v = 50.0 + (py + 0.5 - cy - oy) * inv
        return _coverage(_mark_sdf_svg(u, v) * unit)
    hits = 0
    step = 1.0 / ss
    for iy in range(ss):
        v = 50.0 + (py + (iy + 0.5) * step - cy - oy) * inv
        for ix in range(ss):
            u = 50.0 + (px + (ix + 0.5) * step - cx) * inv
            if _mark_sdf_svg(u, v) <= 0.0:
                hits += 1
    return hits / (ss * ss)


def _render(size: int) -> bytes:
    """RGBA pixel bytes for one icon size: a single flat ICON_BG rounded square
    on a transparent background, with the black scales mark composited over
    it. One colour behind the mark, edge to edge -- see 15.7.4."""
    cx = cy = size / 2.0

    outer_half = size * 0.44
    outer_radius = outer_half * 0.42

    # Supersample the mark only where its thin members would otherwise vanish.
    if size <= 128:
        ss = 4
    elif size <= 256:
        ss = 2
    else:
        ss = 1

    mx0, my0, mx1, my1 = _mark_bbox_px(size)

    pixels = bytearray(size * size * 4)
    for py in range(size):
        y = py + 0.5 - cy
        mark_row = my0 <= y <= my1
        for px in range(size):
            x = px + 0.5 - cx

            outer_d = _rounded_box_sdf(x, y, outer_half, outer_half, outer_radius)
            alpha = _coverage(outer_d)
            offset = (py * size + px) * 4
            if alpha <= 0.0:
                continue

            r, g, b = float(ICON_BG[0]), float(ICON_BG[1]), float(ICON_BG[2])

            if mark_row and mx0 <= x <= mx1:
                mark_t = _mark_coverage(px, py, cx, cy, size, ss)
                if mark_t > 0.0:
                    r += (MARK_INK[0] - r) * mark_t
                    g += (MARK_INK[1] - g) * mark_t
                    b += (MARK_INK[2] - b) * mark_t

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
