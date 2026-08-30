#!/usr/bin/env python3
"""Fail the build if any Mach-O in the bundle targets a newer macOS than we ship for.

See DECISIONS.md 15.8. This is the check that would have caught REVIEW.md
BLOCKER 1: two Homebrew OpenSSL dylibs carrying `LC_BUILD_VERSION minos 26.0`
went out in a bundle nobody could run below macOS 26, and dyld's refusal happens
at `import ssl` -- upstream of every line of our own code, so the recipient sees
one Dock bounce and nothing else.

Stdlib only (struct + pathlib), same rule scripts/make_icon.py follows: a build
check is not a reason to grow a dependency. It also deliberately does not shell
out to `otool` or `vtool` -- those need the Xcode command line tools, and a
check that silently does not run on a machine missing them is not a check.

    packaging/check_deployment_target.py --max 11.0 <path> [<path> ...]
    packaging/check_deployment_target.py --max 11.0 --report <path>

A path may be a directory, a single file, or a **.zip** -- the last because the
zip is what actually gets AirDropped, and BLOCKER 1 was present in the zip as
well as in `packaging/dist/`. Members are read out of the archive in memory; the
zip is never extracted.

Exit 0 if every Mach-O found is at or below --max, 1 otherwise, 2 on usage
error. A path with no Mach-O files in it at all is an error too: a scanner that
happily reports "all clear" because it was pointed at the wrong directory is the
same silence this exists to remove.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import zipfile
from pathlib import Path

# Mach-O magics. The BE/LE pairs are the same file read from either endianness;
# on arm64 and x86_64 only the LE ones occur, but reading both costs nothing and
# means a fat slice for some other machine is reported rather than skipped.
MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF
FAT_CIGAM_64 = 0xBFBAFECA

LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32

PLATFORM_MACOS = 1

# CPU_TYPE_* -> the name `lipo` and `file` use, so a report can be diffed
# against them by eye.
CPU_NAMES = {
    0x0100000C: "arm64",
    0x0000000C: "arm",
    0x01000007: "x86_64",
    0x00000007: "i386",
}


class NotMachO(Exception):
    """The file does not start with a Mach-O or fat magic."""


def decode_version(packed: int) -> tuple[int, int, int]:
    """X.Y.Z packed as nibbles: xxxx.yy.zz."""
    return (packed >> 16) & 0xFFFF, (packed >> 8) & 0xFF, packed & 0xFF


def format_version(v: tuple[int, int, int]) -> str:
    major, minor, patch = v
    return f"{major}.{minor}" if patch == 0 else f"{major}.{minor}.{patch}"


def parse_version_arg(text: str) -> tuple[int, int, int]:
    parts = text.split(".")
    if not 1 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(f"not a macOS version: {text!r}")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a macOS version: {text!r}") from None
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def _slice_minos(data: bytes, offset: int) -> tuple[str, tuple[int, int, int] | None]:
    """Read one thin Mach-O slice: its arch name and its macOS minimum, if any.

    Returns (arch, None) for a slice that declares no macOS minimum at all --
    which is normal for a very old binary and is not a failure.
    """
    (magic,) = struct.unpack_from("<I", data, offset)
    if magic in (MH_MAGIC_64, MH_MAGIC):
        endian, is64 = "<", magic == MH_MAGIC_64
    elif magic in (MH_CIGAM_64, MH_CIGAM):
        endian, is64 = ">", magic == MH_CIGAM_64
    else:
        raise NotMachO(f"slice magic {magic:#010x}")

    # mach_header[_64]: magic, cputype, cpusubtype, filetype, ncmds,
    # sizeofcmds, flags, [reserved]
    cputype, _cpusubtype, _filetype, ncmds, _sizeofcmds, _flags = struct.unpack_from(
        endian + "iiIIII", data, offset + 4
    )
    arch = CPU_NAMES.get(cputype & 0xFFFFFFFF, f"cputype-{cputype}")
    pos = offset + (32 if is64 else 28)

    minos: tuple[int, int, int] | None = None
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from(endian + "II", data, pos)
        if cmdsize < 8:
            raise NotMachO(f"load command size {cmdsize}")
        if cmd == LC_BUILD_VERSION:
            platform, packed, _sdk = struct.unpack_from(endian + "III", data, pos + 8)
            if platform == PLATFORM_MACOS:
                # LC_BUILD_VERSION wins over LC_VERSION_MIN_MACOSX when a binary
                # carries both: it is the modern command, and it is the one that
                # said 26.0 on the dylibs that caused BLOCKER 1 while the legacy
                # command beside it still said 10.13.
                return arch, decode_version(packed)
        elif cmd == LC_VERSION_MIN_MACOSX:
            (packed,) = struct.unpack_from(endian + "I", data, pos + 8)
            minos = decode_version(packed)
        pos += cmdsize
    return arch, minos


def read_minos(data: bytes) -> list[tuple[str, tuple[int, int, int] | None]]:
    """Every (arch, macOS minimum) these bytes declare. Raises NotMachO if not a Mach-O."""
    if len(data) < 8:
        raise NotMachO("too short")

    (magic,) = struct.unpack_from(">I", data, 0)
    if magic in (FAT_MAGIC, FAT_MAGIC_64, FAT_CIGAM, FAT_CIGAM_64):
        # fat_header is always big-endian; FAT_CIGAM* means a little-endian
        # writer, which does not occur on any Mac this ships to, but read it.
        endian = ">" if magic in (FAT_MAGIC, FAT_MAGIC_64) else "<"
        is64 = magic in (FAT_MAGIC_64, FAT_CIGAM_64)
        (nfat,) = struct.unpack_from(endian + "I", data, 4)
        entry = struct.Struct(endian + ("iiQQI" if is64 else "iiIII"))
        out = []
        pos = 8
        for _ in range(nfat):
            _cputype, _sub, off, _size, _align = entry.unpack_from(data, pos)
            out.append(_slice_minos(data, off))
            pos += entry.size
        return out

    return [_slice_minos(data, 0)]


def walk_macho(roots: list[Path]):
    """Yield (display path, results) for every Mach-O under the given roots.

    Symlinks are not followed and not reported: a PyInstaller .app is full of
    them (Contents/MacOS points into Contents/Frameworks), and following them
    would count the same binary twice and let the walk escape the bundle. A zip
    stores symlinks as tiny members whose contents are the link target, so they
    fall out there by simply not being Mach-O.
    """
    for root in roots:
        if root.is_file() and zipfile.is_zipfile(root):
            with zipfile.ZipFile(root) as zf:
                for info in sorted(zf.infolist(), key=lambda i: i.filename):
                    if info.is_dir():
                        continue
                    try:
                        results = read_minos(zf.read(info))
                    except (NotMachO, struct.error, OSError, zipfile.BadZipFile):
                        continue
                    yield f"{root.name}:{info.filename}", results
            continue

        if root.is_file() and not root.is_symlink():
            files = [root]
        else:
            files = []
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
                for name in sorted(filenames):
                    p = Path(dirpath) / name
                    if not p.is_symlink():
                        files.append(p)
        for p in files:
            try:
                results = read_minos(p.read_bytes())
            except (NotMachO, struct.error, OSError):
                continue
            yield p, results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", required=True, type=parse_version_arg, metavar="VERSION",
                    help="the declared deployment target, e.g. 11.0")
    ap.add_argument("--expect-arch", metavar="ARCH", default=None,
                    help="also fail if any slice is not this architecture, e.g. arm64. "
                         "The spec's target_arch=None resolves to the build process's own "
                         "architecture, which a universal2 interpreter makes inheritable "
                         "(DECISIONS.md 15.8), so the artifact is where it is worth asserting.")
    ap.add_argument("--report", action="store_true", help="print every Mach-O found, not just violations")
    ap.add_argument("--relative-to", type=Path, default=None, help="print paths relative to this")
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args(argv)

    for p in args.paths:
        if not p.exists():
            print(f"check_deployment_target: no such path: {p}", file=sys.stderr)
            return 2

    base = args.relative_to
    rows: list[tuple[str, str, tuple[int, int, int] | None]] = []
    for path, results in walk_macho(args.paths):
        if base and isinstance(path, Path) and path.is_relative_to(base):
            shown = str(path.relative_to(base))
        else:
            shown = str(path)
        for arch, minos in results:
            rows.append((shown, arch, minos))

    if not rows:
        print("check_deployment_target: no Mach-O files found -- wrong path?", file=sys.stderr)
        return 2

    violations = [(f, a, m) for f, a, m in rows if m is not None and m > args.max]
    known = [(f, a, m) for f, a, m in rows if m is not None]
    unversioned = [(f, a) for f, a, m in rows if m is None]

    if args.report:
        width = max(len(f) for f, _, _ in rows)
        for f, a, m in sorted(rows, key=lambda r: ((r[2] or (0, 0, 0)), r[0]), reverse=True):
            print(f"  {format_version(m) if m else '(none)':>7}  {a:<8} {f:<{width}}")
        print()

    if known:
        worst = max(m for _, _, m in known)
        carriers = sorted({f for f, _, m in known if m == worst})
        print(f"Deployment target: {len(rows)} Mach-O slices scanned, "
              f"maximum minos {format_version(worst)} (declared target {format_version(args.max)}).")
        print(f"  highest carried by: {carriers[0]}"
              + (f" (and {len(carriers) - 1} more)" if len(carriers) > 1 else ""))
    if unversioned:
        print(f"  {len(unversioned)} slice(s) declare no macOS minimum at all (fine; not a target).")

    wrong_arch = [(f, a) for f, a, _ in rows if args.expect_arch and a != args.expect_arch]
    if wrong_arch:
        sys.stdout.flush()
        print("", file=sys.stderr)
        print(f"ARCHITECTURE CHECK FAILED: {len(wrong_arch)} slice(s) are not {args.expect_arch}.",
              file=sys.stderr)
        print("", file=sys.stderr)
        for f, a in sorted(set(wrong_arch))[:20]:
            print(f"  {a:<8} {f}", file=sys.stderr)
        if len(set(wrong_arch)) > 20:
            print(f"  ... and {len(set(wrong_arch)) - 20} more", file=sys.stderr)
        print("", file=sys.stderr)
        print("See DECISIONS.md 15.8: the spec leaves target_arch=None, which PyInstaller", file=sys.stderr)
        print("resolves to the architecture the BUILD PROCESS is running as.", file=sys.stderr)
        return 1

    if violations:
        # stdout is block-buffered when piped and stderr is not, so the failure
        # block would otherwise print above the report it refers to.
        sys.stdout.flush()
        print("", file=sys.stderr)
        print(f"DEPLOYMENT TARGET CHECK FAILED: {len(violations)} slice(s) target a macOS newer "
              f"than {format_version(args.max)}.", file=sys.stderr)
        print("", file=sys.stderr)
        for f, a, m in sorted(violations, key=lambda r: (r[2], r[0]), reverse=True):
            print(f"  minos {format_version(m):<7} {a:<8} {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print("dyld refuses to load a Mach-O built for a newer macOS than the one running.", file=sys.stderr)
        print("A bundle carrying one of these dies at import on the recipient's Mac, before", file=sys.stderr)
        print("any of our code runs -- one Dock bounce, no window, no log. See DECISIONS.md 15.8.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
