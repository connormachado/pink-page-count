"""Guards on the frozen-bundle build. See DECISIONS.md 15.

These do not build a bundle -- that takes a minute and needs npm. They guard the
two things about the build that can rot silently in an ordinary code change and
would not be noticed until a recipient's Mac:

1. the hidden-import list drifting away from what uvicorn actually resolves
   (AUDIT.md B6: "builds cleanly and then fails at startup"), and
2. the launcher growing a second opinion about which host to bind.

Same AST-inspection spirit as tests/test_quotes.py's import-list check.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "packaging" / "PinkPageCount.spec"
LAUNCHER = REPO_ROOT / "app" / "launcher.py"
ENTRY = REPO_ROOT / "packaging" / "entry.py"


def _spec_list(name: str) -> list:
    """Pull a top-level list literal out of the spec without executing it.

    The spec cannot simply be imported: PyInstaller injects `SPECPATH` and the
    `Analysis`/`EXE`/`BUNDLE` builtins at build time, so exec'ing it raises.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found as a top-level assignment in {SPEC.name}")


def _spec_datas() -> list[tuple[str, str]]:
    """Pull the `datas` list out of the spec as (source-text, destination) pairs.

    `datas` cannot go through `literal_eval`: its sources are `str(REPO / ...)`
    calls, not literals. Only the destination has to be a literal, and that is
    the half these tests care about.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "datas" for t in node.targets
        ):
            pairs = []
            for element in node.value.elts:
                source, destination = element.elts
                pairs.append((ast.unparse(source), ast.literal_eval(destination)))
            return pairs
    raise AssertionError(f"datas not found as a top-level assignment in {SPEC.name}")


def _uvicorn_modules_actually_imported() -> set[str]:
    """The uvicorn submodules the launcher's own Config resolves by string name."""
    import sys

    import uvicorn

    async def dummy(scope, receive, send):  # never mounted, never serves
        pass

    before = set(sys.modules)
    # The same knobs app/launcher.py uses: everything left at "auto".
    cfg = uvicorn.Config(dummy, host="127.0.0.1", port=8420, log_level="warning")
    cfg.load()
    cfg.get_loop_factory()
    return {m for m in set(sys.modules) - before if m.startswith("uvicorn.")}


def test_spec_hidden_imports_cover_everything_uvicorn_resolves():
    """Every uvicorn module reached by string name must be a declared hidden import.

    This is the test that matters. PyInstaller cannot follow
    `import_from_string`, so anything missing here produces a bundle that builds
    without a warning and dies on launch (AUDIT.md B6).
    """
    declared = set(_spec_list("hiddenimports"))
    resolved = _uvicorn_modules_actually_imported()

    # A parent package needs no declaration of its own: PyInstaller pulls in the
    # packages along the path to any module it includes. Only leaves matter.
    parents = {m for m in resolved if any(d.startswith(m + ".") for d in resolved)}

    missing = resolved - declared - parents
    assert not missing, (
        "uvicorn resolves these by string name but the spec does not declare them "
        f"as hidden imports, so the frozen app would fail at startup: {sorted(missing)}"
    )


def test_spec_declares_no_unreachable_hidden_imports():
    """The converse: the list stays an enumeration, not a wishlist.

    DECISIONS.md 15.3 says the impl modules for absent options (uvloop,
    httptools, websockets, wsproto) are deliberately not listed. If one appears
    here, either a dependency was added -- in which case 15.3's table is stale --
    or someone pasted a list from memory.
    """
    declared = set(_spec_list("hiddenimports"))
    never_reachable = {
        "uvicorn.loops.uvloop",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.protocols.websockets.websockets_sansio_impl",
    }
    unreachable = declared & never_reachable
    assert not unreachable, (
        "these cannot be reached with the current requirements.txt; "
        f"remove them or update DECISIONS.md 15.3: {sorted(unreachable)}"
    )


def test_spec_bundles_the_read_only_resources():
    """quotes.txt and web/dist must land where config's defaults look (14, 15.3)."""
    datas = _spec_datas()
    destinations = {dest for _src, dest in datas}
    assert "." in destinations, "quotes.txt must be bundled at RESOURCE_ROOT"
    assert "web/dist" in destinations, "the built front end must be bundled"

    sources = " ".join(src for src, _dest in datas)
    assert "quotes.txt" in sources


def test_spec_bundles_nothing_writable():
    """None of the three data files may ever ship inside the bundle (14)."""
    datas = _spec_datas()
    shipped = " ".join(f"{src} {dest}" for src, dest in datas)
    for never in ("entries.json", "classes.json", "settings.json", "my-quotes.txt"):
        assert never not in shipped, f"{never} belongs in DATA_ROOT, not the bundle"


def test_launcher_binds_only_through_config_host():
    """config.HOST must be the single authority on the bind (15.2).

    run.command:107 passes a literal `--host 127.0.0.1` on a command line, which
    is why the frozen path deliberately does not use the uvicorn CLI. A literal
    address appearing in the launcher would recreate exactly the second source of
    truth this module exists to remove.
    """
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))

    host_values = [
        kw.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "host"
    ]
    assert host_values, "the launcher never passes a host= anywhere"
    for value in host_values:
        assert isinstance(value, ast.Attribute) and value.attr == "HOST", (
            "host= must be config.HOST, never a literal or a computed value"
        )

    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "0.0.0.0" not in literals, "DECISIONS.md 5: never 0.0.0.0"


def test_launcher_does_not_shell_out_to_the_uvicorn_cli():
    """No subprocess, and no `app.main:create_default_app` import-string (15.2)."""
    source = LAUNCHER.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "subprocess" not in imported, "the frozen app must not shell out to uvicorn"

    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "app.main:create_default_app" not in literals, (
        "pass the factory as a callable; a string goes through import_from_string, "
        "which PyInstaller cannot trace (15.3)"
    )


def test_pyinstaller_entry_script_is_a_stub():
    """packaging/entry.py must hold no launch logic of its own (15.2)."""
    tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert not functions, "entry.py is a stub; behavior belongs in app/launcher.py"


def test_pyinstaller_is_not_a_runtime_dependency():
    """requirements.txt stays the minimum run.command installs (15.4)."""
    runtime = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pyinstaller" not in runtime

    build = (REPO_ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()
    assert "pyinstaller" in build


def test_no_app_module_imports_pyinstaller():
    """Nothing the server runs may depend on the thing that packages it.

    Checked through the import list, not a substring search: `config.py` names
    PyInstaller in a comment explaining `sys._MEIPASS` (14), and a prose mention
    is not a dependency.
    """
    for module in sorted((REPO_ROOT / "app").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "PyInstaller" not in imported, f"{module.name} imports PyInstaller"


@pytest.mark.parametrize(
    "path",
    [
        REPO_ROOT / "packaging" / "build_app.sh",
        REPO_ROOT / "packaging" / "PinkPageCount.spec",
        REPO_ROOT / "packaging" / "entry.py",
        REPO_ROOT / "app" / "launcher.py",
    ],
)
def test_build_machinery_is_present(path: Path):
    assert path.is_file(), f"missing build machinery: {path}"
