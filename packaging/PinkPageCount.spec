# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Pink Page Count .app bundle. See DECISIONS.md 15.

Build it with `packaging/build_app.sh`, never by calling pyinstaller by hand --
the script is what guarantees `web/dist` is not stale (15.4).

**onedir, not onefile.** A onefile bundle unpacks itself into a `sys._MEIPASS`
temp directory that is deleted when the process exits; that directory is the
exact mechanism behind AUDIT.md B1's data-loss case, and it makes every launch
pay the unpack cost. onedir has neither problem. See DECISIONS.md 15.1.
"""

from pathlib import Path

# SPECPATH is injected by PyInstaller: the directory holding this spec file.
REPO = Path(SPECPATH).resolve().parent

APP_NAME = "Pink Page Count"
BUNDLE_ID = "com.connormachado.pinkpagecount"
VERSION = "1.0.0"

# -- datas: the read-only resources RESOURCE_ROOT resolves against (14, 15.3) --
#
# The destination paths here are what make config.RESOURCE_ROOT correct in the
# frozen build: `quotes.txt` lands at RESOURCE_ROOT/quotes.txt and the built
# front end at RESOURCE_ROOT/web/dist, which is exactly what
# config.DEFAULT_QUOTES_FILE and config.DEFAULT_DIST_DIR ask for. Neither path
# needs a frozen-only special case anywhere in app/.
#
# Nothing writable is bundled. The three data files and my-quotes.txt live in
# DATA_ROOT and are never shipped (14).
datas = [
    (str(REPO / "quotes.txt"), "."),
    (str(REPO / "web" / "dist"), "web/dist"),
]

# -- hidden imports ------------------------------------------------------- #
#
# uvicorn resolves its protocol, loop and lifespan classes from strings in
# `uvicorn.config` (HTTP_PROTOCOLS, WS_PROTOCOLS, LIFESPAN, LOOP_FACTORIES) via
# `import_from_string`, which PyInstaller's static analysis cannot follow --
# AUDIT.md B6's "builds cleanly and then fails at startup".
#
# This list is not copied from anywhere. It is the set of modules that the exact
# `uvicorn.Config` in app/launcher.py actually imports, observed by diffing
# sys.modules across `Config.load()` + `Config.get_loop_factory()` on this
# venv. With neither uvloop, httptools, wsproto nor websockets installed (none
# is a dependency of this project -- requirements.txt is fastapi + uvicorn), the
# three "auto" resolvers settle deterministically:
#
#   loop  auto -> asyncio  (uvloop absent)
#   http  auto -> h11      (httptools absent)
#   ws    auto -> None     (websockets and wsproto both absent)
#
# so the impl modules for those absent options are deliberately NOT listed: they
# cannot be reached, and listing them would only bloat the bundle and emit
# missing-module warnings for libraries this project does not depend on.
#
# h11 itself is absent from this list on purpose -- `uvicorn.protocols.http
# .h11_impl` imports it with an ordinary `import h11`, so tracing follows it
# once that module is named here. Same for `click`, which `uvicorn/__init__.py`
# reaches statically through `uvicorn.main`.
#
# hooks-contrib ships a `hook-uvicorn.py` that does a blanket
# `collect_submodules('uvicorn')` and would happen to cover these too. This list
# is still explicit and is the contract: it must not silently become a
# dependency on that hook continuing to exist, or on its behavior.
hiddenimports = [
    # the three "auto" resolvers -- the entry points that pick an impl
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    # what they actually resolve to here
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    # imported by h11_impl / shared by the protocol implementations
    "uvicorn.protocols.http.flow_control",
    "uvicorn.protocols.utils",
    # lifespan "auto" -> on
    "uvicorn.lifespan.on",
]

# -- excludes -------------------------------------------------------------- #
# Test and GUI-toolkit machinery that nothing in app/ imports. Excluded for size
# only; none of this is on any code path the app can reach.
excludes = [
    "tkinter",
    "pytest",
    "_pytest",
    "httpx",
    "PIL",
]

a = Analysis(
    [str(REPO / "packaging" / "entry.py")],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: the libraries live beside the executable
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No terminal window on a Finder launch.
    #
    # Note what this does NOT buy: neither this flag nor the .app wrapper makes
    # the process a GUI application. Nothing here ever calls into AppKit, so the
    # process never registers with the window server -- measured, not assumed:
    # a running instance appears in System Events as neither an application
    # process nor a background-only one. **There is therefore no Dock icon and
    # no menu bar, so the user has no way to quit it.** That is the open problem
    # recorded in DECISIONS.md 15.5; it is not fixed here.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # host arch; see 15.6 on the Intel-Mac limitation
    codesign_identity=None,  # not signed, not notarized -- 15.6
    entitlements_file=None,
    icon=str(REPO / "AppIcon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(REPO / "AppIcon.icns"),
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        # The app serves 127.0.0.1 over plain http and must never need the
        # network (DECISIONS.md 5, 9.4). This does not open anything up: it
        # permits loopback only, and the browser -- not this process -- is what
        # loads the page.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
