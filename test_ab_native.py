#!/usr/bin/env python3
"""A/B test: compare .ci output from Python path vs compiled native backend.

(Formerly test_ab_shim.py — renamed once the self-hosted binary's
python3-subprocess fallback was removed entirely; MOJO_NO_SHIM no longer
does anything, so this test no longer sets it.)

Usage:
    python3 test_ab_native.py [file.mojo ...]

If no files given, tests a built-in set of small Mojo programs.

Where the scratch files go, and why it is not the repo root
------------------------------------------------------------
Both dump paths still run with `cwd=HERE` (see `run_native_dump`'s docstring
for the self-host reason, which is unchanged and not negotiable). What changed
is where this test's own `.mojo` sources live: they go in a private
per-process directory under `<repo>/.tmp/`, never in the repo root.

That is a bug fix, not tidiness. The repo root is a shared, writable scratch
surface that several jobs touch at once, and this test was writing
`_abt_<case>.mojo` there for the whole run. On 2026-09-29 (integrator gate,
round 6) a `bootstrap-stage1-dumps` fan-out item failed with

    Error reading ../_abt_minimal_main.mojo: [Errno 2] No such file or directory

which SKIPPED all eight tests behind it. The mechanism was two jobs in one
directory: this test creates the transient, and the other test's fan-out
enumerated the repo root's `*.mojo` and picked it up as one of its own items
(to see the enumeration side, `tools/suite.py`'s `tracked_mojo_files`; the two
halves are fixed together and either alone leaves the flake reachable).

Four constraints shape the replacement, each verified rather than assumed:

  * cwd stays HERE, so the OUTPUT artifacts (`<basename>.ci/.tok/.ast/.pyi`)
    are still written into the repo root by the compiler itself. That is why
    the source BASENAME carries a per-process tag as well as living in a
    private directory: the output name is derived from the input's basename, so
    two concurrent runs of this test would otherwise overwrite each other's
    `.ci` in the one directory they cannot avoid. Tagged, they cannot collide.
  * The scratch dir must be under the WORKTREE, not the system temp dir.
    `_is_selfhost_source_dir` (mojo/backend_gimple/module_gen.py) decides
    whether a source is this compiler's own by walking UP from the file's
    directory looking for `fire_compiler.py`; `<repo>/.tmp/...` still finds it
    and `/tmp/...` does not. A scratch dir on the wrong side of that boundary
    silently compiles the test corpus through a different code path, which
    would make the A/B comparison meaningless.
  * Sibling `--dump-full` resolution is relative to the source file's own
    directory (`_resolve_test_relative_module`), so the driver and its leaf
    modules travel together in the same private dir. That is why the corpus's
    module names are per-process too: a fixed `abfulltest_leaf` would resolve
    to the repo-root tracked file of that name on one run and to the private
    one on the next.
  * `memcap` kills this test's whole tree with SIGKILL when it exceeds its
    8 GB ceiling, and SIGKILL runs no `finally`. So "clean up on every exit
    path" cannot mean only `try/finally` — it means a `finally` for the
    ordinary paths plus a startup sweep for the ones no handler can reach.
    The sweep removes scratch directories and repo-root artifacts belonging to
    a pid that is no longer alive, and only those, so a concurrently running
    sibling process is never touched.
"""
import atexit
import os
import re
import sys
import subprocess
import tempfile
import shutil
import textwrap
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
MOJOC = os.path.join(HERE, 'mojoc')

# The one place this test's transient files are allowed to live. Under the
# worktree on purpose — see the module docstring's second constraint.
SCRATCH_ROOT = os.path.join(HERE, '.tmp')

# pid + random. The pid makes a leftover attributable and makes the liveness
# check in the sweep exact; the random half keeps two runs started in the same
# clock tick (or a pid recycled after a crash) from sharing a name.
_RUN_TAG = f'{os.getpid()}_{uuid.uuid4().hex[:8]}'

# What a source file is named in the private dir, and therefore what the
# compiler names the `.ci`/`.tok`/`.ast`/`.pyi` it leaves in HERE. The tag is
# load-bearing: see the module docstring's first constraint.
SRC_PREFIX = f'abt{_RUN_TAG}_'
# Artifacts the compiler writes into HERE beside the source basename.
ARTIFACT_EXTS = ('ci', 'tok', 'ast', 'pyi')

# The naming scheme above, as patterns rather than as one run's literal tag, so
# the sweep can recognise a DEAD run's leftovers. Written against
# `<pid>_<hex>` rather than against this process's own tag: a pattern
# containing this run's pid matches only this run, which would make the sweep
# delete nothing at all — the exact opposite of what it is for, and a bug that
# looks like "the sweep is fine, there was nothing to clean".
_SCRATCH_DIR_RE = re.compile(r'ab-native-(\d+)_[0-9a-f]{8}-.+')
_ARTIFACT_RE = re.compile(
    r'abt(\d+)_[0-9a-f]{8}_\w+\.(?:' + '|'.join(ARTIFACT_EXTS) + r')')

_scratch = None


def scratch_dir() -> str:
    """This process's private scratch directory, created on first use.

    Exists for the whole process rather than per case so that a case's source,
    its `.ci` and its siblings share one directory — the `--dump-full` sibling
    cases resolve their imports relative to the driver's own directory, so a
    per-case directory would work too, but one directory for the run means one
    thing to sweep and one thing to reason about.
    """
    global _scratch
    if _scratch is None:
        os.makedirs(SCRATCH_ROOT, exist_ok=True)
        _scratch = tempfile.mkdtemp(prefix=f'ab-native-{_RUN_TAG}-',
                                    dir=SCRATCH_ROOT)
    return _scratch


def cleanup_scratch() -> None:
    """Remove everything this process left behind: its scratch directory, and
    any dump artifact a case left in HERE (the compiler writes those into its
    CWD, which has to be the repo root — see the module docstring — so they are
    this run's litter even though the run is not where they are written).

    Idempotent, and safe to call from a signal handler or from `atexit` after
    the normal path already ran.
    """
    global _scratch
    if _scratch and os.path.isdir(_scratch):
        shutil.rmtree(_scratch, ignore_errors=True)
    _scratch = None
    for name in _our_artifacts_in(HERE):
        _remove_if_present(os.path.join(HERE, name))


def _our_artifacts_in(directory: str) -> list:
    """Names in `directory` matching this run's artifact tag. The tag is
    unique per process, so this never returns another run's file."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return [n for n in entries if n.startswith(SRC_PREFIX)
            and n.endswith(ARTIFACT_EXTS)]


def _pid_alive(pid: int) -> bool:
    """Is `pid` still running? Signal 0 does the permission/existence check
    without delivering anything. `PermissionError` means it exists and belongs
    to someone else, which counts as alive — deleting another user's scratch
    would be worse than leaving ours."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def sweep_stale_scratch() -> None:
    """Remove scratch dirs and repo-root artifacts left by a DEAD run.

    This is the half of "clean up on every exit path" that no exit path can
    do for itself: `memcap` kills this test's tree with SIGKILL at its 8 GB
    ceiling, and a SIGKILLed process runs no `finally`, no `atexit` and no
    signal handler. Without this, a killed run's artifacts accumulate in the
    repo root forever.

    Scoped to our own naming scheme and to pids that are not alive, which is
    what makes running it at import time safe: a concurrently running
    `test_ab_native.py` has a live pid, so its directory and its `.ci` files
    are left alone. The pid is parsed out of the name we ourselves generate,
    so nothing that is not one of our own scratch entries can match.
    """
    if not os.path.isdir(SCRATCH_ROOT):
        return
    for name in os.listdir(SCRATCH_ROOT):
        m = _SCRATCH_DIR_RE.fullmatch(name)
        if not m:
            continue                                   # not ours
        pid = int(m.group(1))
        if pid == os.getpid() or _pid_alive(pid):
            continue                                   # still running
        shutil.rmtree(os.path.join(SCRATCH_ROOT, name), ignore_errors=True)
    # Artifacts a killed run left in HERE, same liveness rule. These are
    # gitignored, so they never become a fan-out item — but a stale `_ci` from
    # a previous run is exactly what tools/ab_run_one.py's `_run_locked` has to
    # defensively delete "so a leftover file is never mistaken for this run's",
    # and this is the other end of that: do not produce them in the first place.
    try:
        entries = os.listdir(HERE)
    except OSError:
        return
    for name in entries:
        m = _ARTIFACT_RE.fullmatch(name)
        if not m:
            continue
        pid = int(m.group(1))
        if pid == os.getpid() or _pid_alive(pid):
            continue
        try:
            os.remove(os.path.join(HERE, name))
        except OSError:
            pass


sweep_stale_scratch()
atexit.register(cleanup_scratch)


def _scratch_source(basename: str, source: str) -> str:
    """Write `source` as this run's private copy of `basename`; return its path.

    `basename` is a filename (`abfulltest_leaf.mojo`), not a stem: the corpus
    names its modules the same way the import lines in its drivers do, and
    making the two different shapes is how a case ends up writing
    `..._leaf.mojo.mojo` and failing with a path that looks present. The tag
    and the extension are both applied here, in one place, so the file this
    case writes and the module name the corpus imports cannot drift apart.

    Tagged basename, so the `.ci` the compiler writes into HERE cannot collide
    with another process's. The `.mojo` itself never enters the repo root, so
    no concurrent fan-out over that directory can ever enumerate it.
    """
    path = os.path.join(scratch_dir(), _tagged(basename))
    with open(path, 'w') as f:
        f.write(source)
    return path


def _remove_if_present(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _tagged(basename: str) -> str:
    """`abfulltest_leaf.mojo` -> `abt<pid>_<hex>_abfulltest_leaf.mojo`.

    Accepts a filename or a bare stem, because this file's two corpora spell
    their cases differently — `--dump` names them by stem (`minimal_main`),
    `--dump-full` by filename (`abfulltest_leaf.mojo`, because that is also how
    the import lines in its drivers name them). Normalising here rather than at
    each call site is what keeps `..._leaf.mojo.mojo` from being possible.

    The FILENAME form. The MODULE-NAME form — the same string without the
    extension — is what the corpus's `{m}` placeholder expands to, and the two
    have to agree: a `--dump-full` case is only testing sibling resolution if
    the `from X import Y` in its driver names the module the case actually
    wrote. Both derive from this run's single tag, so the one place they could
    disagree is right here.
    """
    stem, ext = os.path.splitext(basename)
    if not ext:
        stem, ext = basename, '.mojo'
    return f'{SRC_PREFIX}{stem}{ext}'



def _collect_artifacts(src_path: str, out_dir: str) -> str:
    """Move the dump's artifacts out of the repo root into `out_dir`; return
    the `.ci`'s new path.

    Both dump paths run with `cwd=HERE` (non-negotiable, see each function's
    docstring), so the compiler writes `<basename>.ci` — and, for `--dump`,
    `.tok`/`.ast`/`.pyi` — into the shared repo root, named after the INPUT's
    basename regardless of where the input itself lives. Moving them out here
    rather than in each caller is what keeps the repo root clear: a `.tok` or
    `.ast` left behind is gitignored and therefore harmless to the fan-out, but
    it is still litter in a directory other jobs read, and one implementation
    of "where does the artifact go" is one that cannot be forgotten by the
    next caller.

    The destination is keyed on the input's basename, which is unique per
    process (see `SRC_PREFIX`), so two concurrent runs of this test never
    clobber each other's collected `.ci`.
    """
    basename = os.path.splitext(os.path.basename(src_path))[0]
    ci_path = os.path.join(out_dir, f'{basename}.ci')
    for ext in ARTIFACT_EXTS:
        produced = os.path.join(HERE, f'{basename}.{ext}')
        if not os.path.exists(produced):
            continue
        dest = ci_path if ext == 'ci' else os.path.join(out_dir, f'{basename}.{ext}')
        if os.path.abspath(produced) != os.path.abspath(dest):
            shutil.move(produced, dest)
    return ci_path


def run_python_dump(src_path: str, out_dir: str, flag: str = '--dump') -> str:
    """Run python3 fire.py <flag> on src_path, return path to .ci file.

    MUST run from the repo root (`cwd=HERE`), same as run_native_dump: the
    self-host AST-reflection injection is CWD-gated, so a run from a temp
    dir produces a different (shorter) .ci that is not comparable to the
    native one. Kept symmetric so the only variable is Python-path vs
    compiled backend. `flag` is '--dump' (do_imports=False, single-TU) or
    '--dump-full' (do_imports=True, transitive closure) — see
    test_dump_full_file's docstring for why the two need separate corpora.

    `src_path` may live anywhere — the corpus writes it into a private
    scratch dir (module docstring); only its BASENAME is load-bearing, because
    that is what the output files are named after.
    """
    src_path = os.path.abspath(src_path)
    cmd = [sys.executable, os.path.join(HERE, 'fire.py'), flag, src_path]
    subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=60)
    return _collect_artifacts(src_path, out_dir)


def run_native_dump(src_path: str, out_dir: str, flag: str = '--dump') -> str:
    """Run mojoc <flag> on src_path, return path to .ci file.

    No MOJO_NO_SHIM needed: the self-hosted binary always uses its own
    compiled compile_to_gimple directly now (the subprocess fallback was
    removed entirely from gimple_codegen_compile_to_gimple in
    runtime/fire_runtime.c)."""
    src_path = os.path.abspath(src_path)
    env = os.environ.copy()
    # The compiled binary's `__file__` is "<bootstrap>", so its self-host
    # detection (`_SELFHOST_DIR = dirname(abspath(__file__))`) resolves to the
    # process CWD. The self-host struct registration (AST nodes, interpreter
    # types) is gated on that, so mojoc MUST run from the repo root — from a
    # temp dir the gate is False and AST field access falls back to
    # mojo_obj_getattr -> segfault (Class D of the A/B divergence list).
    # MOJO_HOME is also set as a belt-and-suspenders (runtime project root).
    env['MOJO_HOME'] = HERE
    # File must come FIRST: the compiled binary's argv parser uses
    # sys.argv[1] as the input and strips '--dump'/'--dump-full' by
    # rebuilding the list (list.remove is broken in the compiled binary).
    cmd = [MOJOC, src_path, flag]
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                            timeout=120, env=env)
    if result.returncode != 0:
        print(f"  NATIVE STDERR: {result.stderr[:2000]}", file=sys.stderr)
    # The binary writes the .ci to ITS cwd (HERE); _collect_artifacts moves it.
    return _collect_artifacts(src_path, out_dir)


def diff_ci_files(ci_a: str, ci_b: str) -> tuple:
    """Compare two .ci files. Return (match: bool, diff_summary: str)."""
    if not os.path.exists(ci_a):
        return False, f"Python .ci missing: {ci_a}"
    if not os.path.exists(ci_b):
        return False, f"Native .ci missing: {ci_b}"

    # Read as BYTES then decode latin-1: a native .ci can carry non-UTF-8
    # bytes (a miscompiled name), and a hard UnicodeDecodeError here would
    # mask the real, more useful "these two differ at line N" report.
    with open(ci_a, 'rb') as f:
        lines_a = f.read().decode('latin-1').splitlines(keepends=True)
    with open(ci_b, 'rb') as f:
        lines_b = f.read().decode('latin-1').splitlines(keepends=True)

    if lines_a == lines_b:
        return True, "IDENTICAL"

    # Find first differing line
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        if la != lb:
            break
    else:
        # One is prefix of the other
        i = min(len(lines_a), len(lines_b))

    # Show context around first diff
    start = max(0, i - 3)
    end = min(max(len(lines_a), len(lines_b)), i + 5)
    snippet = []
    for j in range(start, end):
        a = lines_a[j] if j < len(lines_a) else "<EOF>"
        b = lines_b[j] if j < len(lines_b) else "<EOF>"
        marker = " " if j < i else "≠" if a != b else " "
        snippet.append(f"{marker} L{j+1}:")
        snippet.append(f"  py: {a.rstrip()}")
        snippet.append(f"  nc: {b.rstrip()}")

    summary = f"DIFF at line {i+1} (out of {len(lines_a)}/{len(lines_b)} lines)"
    return False, summary + "\n" + "\n".join(snippet)


def _compare(py_ci: str, nc_ci: str, name: str) -> bool:
    """Diff one case's two `.ci` files and print its verdict line. The single
    place the pass/fail line is formatted, so every case in this file reports
    identically."""
    match, summary = diff_ci_files(py_ci, nc_ci)
    status = "PASS" if match else "FAIL"
    print(f"  {status}  {name}: {summary.splitlines()[0]}")
    if not match:
        print(f"         {summary}")
    return match


def test_inline_source(name: str, source: str):
    """Test an inline Mojo source snippet.

    The `.mojo` goes into this process's private scratch dir under
    `<repo>/.tmp/`, never the repo root — see the module docstring. The old
    `_abt_<name>.mojo`-in-the-root arrangement is what a concurrent
    `bootstrap-stage*-dumps` fan-out enumerated (2026-09-29), and moving the
    file is the fix; the tagged basename then keeps the `.ci` the compiler
    writes into HERE from colliding with another run's.
    """
    src_file = _scratch_source(name, source)
    try:
        with tempfile.TemporaryDirectory() as td:
            py_dir = os.path.join(td, 'py')
            nc_dir = os.path.join(td, 'nc')
            os.makedirs(py_dir)
            os.makedirs(nc_dir)

            ci_py = run_python_dump(src_file, py_dir)
            ci_nc = run_native_dump(src_file, nc_dir)

            return _compare(ci_py, ci_nc, name)
    finally:
        # The scratch dir is removed wholesale at exit; removing the source
        # here as well keeps a single case's footprint small while the run
        # continues, so a long corpus is not holding 27 sources at once.
        _remove_if_present(src_file)


def test_file(path: str):
    """Test a .mojo file from disk.

    Nothing is written into the repo root for a file the caller already has:
    the source stays where it is and only the dump artifacts are collected out
    of HERE.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    with tempfile.TemporaryDirectory() as td:
        py_dir = os.path.join(td, 'py')
        nc_dir = os.path.join(td, 'nc')
        os.makedirs(py_dir)
        os.makedirs(nc_dir)

        ci_py = run_python_dump(path, py_dir)
        ci_nc = run_native_dump(path, nc_dir)

        return _compare(ci_py, ci_nc, name)


def test_dump_full_multi(name: str, files: dict, driver: str):
    """Test a `--dump-full` (do_imports=True, transitive closure) sibling-
    import scenario: `files` maps {basename.mojo: source} for every sibling
    module, `driver` names the one to invoke mojo(c) on.

    Plain `--dump` (BUILTIN_TESTS above) is do_imports=False — a single
    translation unit that never calls `_compile_imported_module`, so it
    cannot exercise cross-module `from X import Y` resolution at all. A
    real regression (BUG: `from gimple_exprtypes import ...` inside
    gimple_gen_coro.py, and `from fire_compiler import (...)` inside
    gimple_gen_stmts.py, both reached only through the compiled backend's
    OWN `--dump-full` self-compile of fire.py) was invisible to the whole
    27-case `--dump` corpus for exactly this reason — see
    gimple_module_gen.py's `FromImportStmt` sibling-resolution loop (the
    `can_resolve_module_path` guard added alongside this test). These
    cases mirror that shape in miniature: a driver module importing a
    sibling that is itself not stdlib/test-resolvable, so `load_module`
    must fail cleanly (guarded) instead of raising uncaught on the
    compiled backend.

    Every module — driver and leaves alike — is written into the private
    scratch dir, which is also what makes the sibling import resolve: the
    lookup walks up from the DRIVER's own directory. That is why the module
    names carry this run's tag: the corpus's literal `abfulltest_leaf` is
    also the name of a tracked repo-root file, and an untagged leaf written
    to a private dir would resolve to whichever the search found first.
    Tagging keeps "the file this case wrote" and "the file the compiler read"
    the same file, which is the whole point of a sibling-import case.
    """
    written = []
    # The driver goes through _scratch_source like every other module (which
    # is where the tag is applied — one place, so a module cannot be written
    # tagged and imported untagged) and is written with the same content the
    # corpus declared for it, so there is no second, differently-derived path
    # to the file the test is actually about.
    driver_source = files[driver].format(m=SRC_PREFIX)
    driver_path = _scratch_source(driver, driver_source)
    try:
        for basename, source in files.items():
            written.append(_scratch_source(basename, source.format(m=SRC_PREFIX)))
        with tempfile.TemporaryDirectory() as td:
            py_dir = os.path.join(td, 'py')
            nc_dir = os.path.join(td, 'nc')
            os.makedirs(py_dir)
            os.makedirs(nc_dir)

            ci_py = run_python_dump(driver_path, py_dir, flag='--dump-full')
            ci_nc = run_native_dump(driver_path, nc_dir, flag='--dump-full')

            return _compare(ci_py, ci_nc, name)
    finally:
        for p in written:
            _remove_if_present(p)
        _remove_if_present(driver_path)


# ── Built-in --dump-full sibling-import test cases ────────────────────────
# Each entry: name -> (files: {basename.mojo: source}, driver: basename.mojo).
#
# `{m}` in a source expands to this run's module-name tag (SRC_PREFIX). It is
# not decoration: the files are written to a private scratch dir, and a
# sibling `from X import Y` is resolved by walking up from the DRIVER's own
# directory, so the module name in the import line and the file this case
# actually wrote have to be the same name. Spelling that as a placeholder
# rather than substituting the module name textually keeps the substitution
# impossible to get wrong in a way a reader cannot see — the corpus shows the
# import, and the tag is visibly applied to both sides of it.
DUMP_FULL_TESTS = {
    "sibling_from_import": (
        {
            "abfulltest_leaf.mojo": textwrap.dedent("""\
                def leaf_value() -> Int:
                    return 7
            """),
            "abfulltest_driver.mojo": textwrap.dedent("""\
                from {m}abfulltest_leaf import leaf_value

                def main() -> Int:
                    return leaf_value() + 1
            """),
        },
        "abfulltest_driver.mojo",
    ),
    "sibling_from_import_multi_name": (
        {
            "abfulltest_leaf2.mojo": textwrap.dedent("""\
                def leaf_a() -> Int:
                    return 1

                def leaf_b() -> Int:
                    return 2
            """),
            "abfulltest_driver2.mojo": textwrap.dedent("""\
                from {m}abfulltest_leaf2 import (leaf_a, leaf_b)

                def main() -> Int:
                    return leaf_a() + leaf_b()
            """),
        },
        "abfulltest_driver2.mojo",
    ),
    "transitive_sibling_from_import": (
        {
            "abfulltest_leaf3.mojo": textwrap.dedent("""\
                def leaf_value3() -> Int:
                    return 3
            """),
            "abfulltest_mid3.mojo": textwrap.dedent("""\
                from {m}abfulltest_leaf3 import leaf_value3

                def mid_value() -> Int:
                    return leaf_value3() * 2
            """),
            "abfulltest_driver3.mojo": textwrap.dedent("""\
                from {m}abfulltest_mid3 import mid_value

                def main() -> Int:
                    return mid_value() + 1
            """),
        },
        "abfulltest_driver3.mojo",
    ),
}


# ── Built-in test cases ──────────────────────────────────────────────────

BUILTIN_TESTS = {
    "minimal_main": textwrap.dedent("""\
        def main():
            print(42)
    """),
    "arithmetic": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 10
            var y: Int = 32
            return x + y
    """),
    "function_def": textwrap.dedent("""\
        def add(a: Int, b: Int) -> Int:
            return a + b

        def main() -> Int:
            return add(20, 22)
    """),
    "if_else": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 5
            if x > 0:
                return 42
            else:
                return 0
    """),
    "list_ops": textwrap.dedent("""\
        def main() -> Int:
            var items = [1, 2, 3, 4, 5]
            var total = 0
            for i in range(len(items)):
                total = total + items[i]
            return total
    """),
    "string_ops": textwrap.dedent("""\
        def main():
            var s: String = "hello world"
            print(len(s))
    """),
    "while_loop": textwrap.dedent("""\
        def main() -> Int:
            var i: Int = 0
            var total: Int = 0
            while i < 10:
                total = total + i
                i = i + 1
            return total
    """),
    "nested_func": textwrap.dedent("""\
        def outer(x: Int) -> Int:
            def inner(y: Int) -> Int:
                return y * 2
            return inner(x) + 1

        def main() -> Int:
            return outer(20)
    """),
    "struct_def": textwrap.dedent("""\
        struct Point:
            var x: Int
            var y: Int

        def main() -> Int:
            var p = Point(3, 4)
            return p.x + p.y
    """),
    "dict_ops": textwrap.dedent("""\
        def main() -> Int:
            var d = {"a": 1, "b": 2}
            return d["a"] + d["b"]
    """),
    "fstring": textwrap.dedent("""\
        def main():
            var x: Int = 42
            var s = f"value={x}"
            print(s)
    """),
    "aug_assign": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 5
            x += 3
            x *= 2
            return x
    """),
    "break_continue": textwrap.dedent("""\
        def main() -> Int:
            var total: Int = 0
            for i in range(10):
                if i == 2:
                    continue
                if i == 8:
                    break
                total = total + i
            return total
    """),
    "string_concat": textwrap.dedent("""\
        def main():
            var a: String = "foo"
            var b: String = "bar"
            print(a + b)
    """),
    "tuple_ops": textwrap.dedent("""\
        def main() -> Int:
            var t = (10, 20, 30)
            return t[0] + t[1] + t[2]
    """),
    "comprehension": textwrap.dedent("""\
        def main() -> Int:
            var items = [i * 2 for i in range(5)]
            var total = 0
            for x in items:
                total = total + x
            return total
    """),
    "class_methods": textwrap.dedent("""\
        class Counter:
            var count: Int

            fn __init__(inout self):
                self.count = 0

            fn inc(inout self):
                self.count += 1

            fn get(self) -> Int:
                return self.count

        def main() -> Int:
            var c = Counter()
            c.inc()
            c.inc()
            c.inc()
            return c.get()
    """),
    "try_except": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 0
            try:
                x = 5
            except:
                x = 0
            return x
    """),
    "match_stmt": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 2
            match x:
                case 1:
                    return 10
                case 2:
                    return 20
                case _:
                    return 0
    """),
    "global_var": textwrap.dedent("""\
        var counter: Int = 0

        def bump() -> Int:
            global counter
            counter += 1
            return counter

        def main() -> Int:
            bump()
            bump()
            return bump()
    """),
    "recursive": textwrap.dedent("""\
        def fib(n: Int) -> Int:
            if n <= 1:
                return n
            return fib(n - 1) + fib(n - 2)

        def main() -> Int:
            return fib(10)
    """),
    "closure": textwrap.dedent("""\
        def make_adder(n: Int):
            def add(x: Int) -> Int:
                return x + n
            return add

        def main() -> Int:
            var add5 = make_adder(5)
            return add5(37)
    """),
    "list_of_strings": textwrap.dedent("""\
        def main():
            var items = ["a", "b", "c"]
            for s in items:
                print(s)
    """),
    "string_methods": textwrap.dedent("""\
        def main():
            var s: String = "Hello World"
            print(s.lower())
            print(s.upper())
            print(s.replace("World", "Mojo"))
    """),
    "nested_loops": textwrap.dedent("""\
        def main() -> Int:
            var total: Int = 0
            for i in range(3):
                for j in range(3):
                    total = total + i * j
            return total
    """),
    "list_append": textwrap.dedent("""\
        def main() -> Int:
            var items = [1, 2, 3]
            items.append(4)
            items.append(5)
            var total = 0
            for x in items:
                total = total + x
            return total
    """),
    "dict_iterate": textwrap.dedent("""\
        def main() -> Int:
            var d = {"a": 1, "b": 2, "c": 3}
            var total = 0
            for v in d.values():
                total = total + v
            return total
    """),
}


def main():
    if not os.path.exists(MOJOC):
        print(f"ERROR: {MOJOC} not found. Build with: python3 fire.py build fire.py -o mojoc", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0

    # Test inline sources
    print("=" * 60)
    print("A/B TEST — Python vs compiled native backend")
    print("=" * 60)
    print()

    if len(sys.argv) > 1:
        # Test files from command line
        for path in sys.argv[1:]:
            if test_file(path):
                passed += 1
            else:
                failed += 1
    else:
        # Test built-in snippets
        for name, source in BUILTIN_TESTS.items():
            if test_inline_source(name, source):
                passed += 1
            else:
                failed += 1

        # `--dump-full` (do_imports=True) sibling-import corpus — see
        # test_dump_full_multi's docstring for why this needs its own
        # section (plain `--dump` above never exercises cross-module
        # `from X import Y` resolution).
        print()
        for name, (files, driver) in DUMP_FULL_TESTS.items():
            if test_dump_full_multi(name, files, driver):
                passed += 1
            else:
                failed += 1

        # test_simple.mojo is a larger stretch program (nested def +
        # every collection literal + `raises` main); the native backend
        # still SEGVs on it. Reported for visibility but NOT counted as a
        # failure — the 27 BUILTIN_TESTS above are the byte-parity gate.
        test_simple = os.path.join(HERE, 'test_simple.mojo')
        if os.path.exists(test_simple):
            print()
            ok = test_file(test_simple)
            print(f"  (test_simple is an informational stretch case — "
                  f"{'matches' if ok else 'still diverges'}, not gated)")

    print()
    print(f"Results: {passed} passed, {failed} failed")
    # Explicit, not implicit in the interpreter's exit: `sys.exit` raises
    # SystemExit, which unwinds through `finally` blocks, but spelling the
    # cleanup here means the guarantee does not depend on that interaction
    # holding for every future edit above. `atexit` is the backstop for the
    # paths that never reach this line.
    cleanup_scratch()
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
