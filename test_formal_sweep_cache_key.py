#!/usr/bin/env python3
"""The formal verdict cache key sees the sources the build COMPILES, and the
sweep's timeout takes the whole process TREE down.

Two instruments, one file, because they are the two ways this sweep could
report a fact about a machine as a fact about a program.

**The cache key.** `cas.formal_build_key`'s docstring used to say that "imported
signatures do not exist here — compile_formal compiles one file and skips its
import statements, so a stdlib edit cannot change this artifact". The first
clause stopped being true when `formal/imports.py` stopped modelling modules and
started COMPILING them: `formal/build.py`'s `_resolve_imports` compiles every
module in the file's transitive closure into a dylib and links it, and a
failure there IS the verdict (that is the whole `codegen/dependency` class).
`formal_fingerprint()` is a `.py` glob over `formal/**`, so
`formal/hostmods/*.mojo` — the one place a module edit lands in practice — was
not in the key at all, and a sweep run right after a fix to one of them printed
`cas: 4 hit` and "verdict history: unchanged: 4" for four files that now build.
The failure is silent in the direction that matters: a sweep says the fix did
nothing.

So the key now folds in `formal.imports.import_closure_digest(path)` — the
transitive closure's content digest, walked with the SAME `imported_modules` /
`resolve_module_path` pair the build walks with, which is why it cannot resolve
a module the build would not have compiled. What is asserted:

  1. editing a `formal/hostmods/*.mojo` moves the digest AND the key, using a
     TEMP hostmods root (`formal.imports._HOSTMODS_ROOT` is read at call time,
     so pointing it at a temp tree exercises the real resolution path without a
     test touching a tracked file);
  2. it did not before — the same two keys computed WITHOUT the new argument are
     equal, which is the bug stated as an assertion rather than as a story;
  3. whether a module RESOLVES is part of it (unresolved ⇒ `not-answerable/
     host-import` is the verdict, so the resolution state is an input);
  4. a file with no imports is unaffected, so the invalidation is confined to
     the files that reach a module;
  5. the sweep passes the digest (`_imports_digest`), and it is the same value.

**The timeout.** `tools/formal_sweep.py`'s per-file timeout was
`subprocess.run(timeout=…)`, which SIGKILLs the process it started and nothing
below it. The direct child is the `memcap` WRAPPER, so a timed-out file killed
the wrapper and left the build running, unmonitored, still holding the memory
the per-file ceiling exists to bound. The child was already in its own session
— which is what makes a group kill possible at all — and nothing was using it.
The test spawns a fake build that starts a grandchild, times out, and requires
the grandchild to be gone.

Usage:
    python3 test_formal_sweep_cache_key.py [-v]
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = HERE
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import cas  # noqa: E402
import formal.imports as I  # noqa: E402
import formal_sweep as S  # noqa: E402

FLAGS = ("--formal", "--no-prove", "--backend=arm64")
CRITERIA = "test"


def check(name, cond, detail=""):
    if cond:
        print(f"PASS  {name}")
        return True
    print(f"FAIL  {name}  {detail}")
    return False


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


# ── the key ────────────────────────────────────────────────────────────────

def with_temp_hostmods(tmpdir, fn):
    """Point the resolver's host-module root at a temp tree, then call `fn`.

    `formal/imports.py` reads `_HOSTMODS_ROOT` inside `_search_roots`, so this
    is the real resolution path — the only thing replaced is where the module
    SOURCE lives. Editing `formal/hostmods/re.mojo` in place would be the other
    way to do this and is not acceptable in a test.
    """
    root = os.path.join(tmpdir, "hostmods")
    write(os.path.join(root, "widget.mojo"),
          "def widget_add(x: Int, y: Int) -> Int:\n    return x + y\n")
    saved = I._HOSTMODS_ROOT
    I._HOSTMODS_ROOT = root
    try:
        return fn(root)
    finally:
        I._HOSTMODS_ROOT = saved


def test_editing_a_hostmod_source_misses(tmpdir):
    """THE case: a `.mojo` under `formal/hostmods/` moves the key."""
    def body(root):
        prog = write(os.path.join(tmpdir, "prog.mojo"),
                     "import widget\n"
                     "def main(n: Int) -> Int:\n"
                     "    return widget_add(n, 1)\n")
        source = open(prog).read()
        before_digest = I.import_closure_digest(prog)
        before_key = cas.formal_build_key(source, prog, FLAGS, CRITERIA,
                                          imports=before_digest)
        # The same two keys WITHOUT the closure argument — what the key was
        # before this clause existed.
        blind_before = cas.formal_build_key(source, prog, FLAGS, CRITERIA)
        # …and now edit the host-module source, which is the whole point.
        write(os.path.join(root, "widget.mojo"),
              "def widget_add(x: Int, y: Int) -> Int:\n"
              "    # the signature got narrower\n"
              "    return x + y\n")
        after_digest = I.import_closure_digest(prog)
        after_key = cas.formal_build_key(source, prog, FLAGS, CRITERIA,
                                         imports=after_digest)
        blind_after = cas.formal_build_key(source, prog, FLAGS, CRITERIA)
        return {
            "digest_moved": before_digest != after_digest,
            "key_moved": before_key != after_key,
            "blind_key_stayed": blind_before == blind_after,
            "closure_not_empty": bool(before_digest),
        }

    r = with_temp_hostmods(tmpdir, body)
    results = [
        check("a_hostmod_source_is_in_the_closure", r["closure_not_empty"]),
        check("editing_a_hostmod_source_moves_the_digest", r["digest_moved"]),
        check("editing_a_hostmod_source_moves_the_key", r["key_moved"]),
        check("without_the_clause_the_key_would_not_have_moved",
              r["blind_key_stayed"]),
    ]
    return all(results)


def test_whether_a_module_resolves_is_in_the_key(tmpdir):
    """Unresolved ⇒ `not-answerable/host-import`, which IS the verdict."""
    prog = write(os.path.join(tmpdir, "unres.mojo"),
                 "import a_module_nobody_wrote\n"
                 "def main(n: Int) -> Int:\n    return n\n")
    before = I.import_closure_digest(prog)
    # Give the name a source in the importer's own directory — pass 1 of the
    # resolver, nearest root first.
    write(os.path.join(tmpdir, "a_module_nobody_wrote.mojo"),
          "def f() -> Int:\n    return 1\n")
    after = I.import_closure_digest(prog)
    return check("a_module_becoming_resolvable_moves_the_digest",
                 before != after and bool(before) and bool(after),
                 f"before={before[:12]} after={after[:12]}")


def test_a_file_with_no_imports_is_unaffected(tmpdir):
    """The invalidation is confined to files that reach a module.

    `''` for an import-free file is what keeps every such verdict's cache entry
    where it was, so adding this clause to the key costs one rebuild for the
    files that import and nothing at all for the ones that do not.
    """
    prog = write(os.path.join(tmpdir, "solo.mojo"),
                 "def main(n: Int) -> Int:\n    return n + 1\n")
    digest = I.import_closure_digest(prog)
    key_new = cas.formal_build_key(open(prog).read(), prog, FLAGS, CRITERIA,
                                   imports=digest)
    key_old = cas.formal_build_key(open(prog).read(), prog, FLAGS, CRITERIA)
    return check("an_import_free_file_keys_exactly_as_it_did",
                 digest == "" and key_new == key_old,
                 f"digest={digest[:12]!r}")


def test_the_sweep_passes_the_digest(tmpdir):
    """`tools/formal_sweep.py` hands the key the same digest, not a copy."""
    prog = write(os.path.join(tmpdir, "prog2.mojo"),
                 "import widget\n"
                 "def main(n: Int) -> Int:\n    return widget_add(n, 2)\n")

    def body(_root):
        return S._imports_digest(prog) == I.import_closure_digest(prog)

    ok = with_temp_hostmods(tmpdir, body)
    ok &= check("the_sweeps_digest_is_the_resolvers_digest", ok)
    # And it degrades rather than failing a sweep: a file that cannot be walked
    # must not be the thing that decides the file's verdict.
    ok &= check("an_unreadable_file_yields_an_empty_digest",
                S._imports_digest(os.path.join(tmpdir, "nope.mojo")) == "")
    return ok


# ── the timeout ────────────────────────────────────────────────────────────

FAKE_BUILD = '''\
import subprocess, sys, time
# A "build" that starts a compiler of its own and then hangs — the shape the
# sweep's timeout has to be able to take down. It prints the grandchild's pid so
# the test can ask whether that pid is still alive afterwards.
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
print("grandchild", child.pid, flush=True)
time.sleep(600)
'''


def test_the_timeout_takes_the_whole_tree(tmpdir):
    argv = S.FIRE
    fake = write(os.path.join(tmpdir, "fake_build.py"), FAKE_BUILD)
    pidfile = os.path.join(tmpdir, "grandchild.pid")
    saved_fire = S.FIRE
    S.FIRE = fake
    try:
        t0 = time.time()
        timed_out = False
        caught = None
        try:
            S._run_build(os.path.join(tmpdir, "prog.mojo"),
                         os.path.join(tmpdir, "out"), FLAGS, timeout=6,
                         mem_gb=0)
        except subprocess.TimeoutExpired as e:
            timed_out, caught = True, e
        secs = time.time() - t0
    finally:
        S.FIRE = saved_fire
    results = [
        check("the_timeout_fires", timed_out, f"{secs:.1f}s"),
        check("the_timeout_is_its_own_bound", secs < 30, f"{secs:.1f}s"),
        check("the_timeout_still_reports_what_the_build_printed",
              caught is not None and "grandchild" in _text_of(caught),
              f"output={getattr(caught, 'output', None)!r}"),
    ]
    # The grandchild pid was printed by the fake build; `_run_build` re-raises
    # with whatever the tree printed, so it is in the exception's output.
    pid = None
    for line in _text_of(caught).splitlines():
        if line.startswith("grandchild "):
            pid = int(line.split()[1])
    if not check("the_fake_build_reported_its_grandchild", pid is not None,
                 "no 'grandchild <pid>' line reached the exception"):
        return all(results)
    alive = _pid_alive(pid)
    deadline = time.time() + 10
    while alive and time.time() < deadline:
        time.sleep(0.2)
        alive = _pid_alive(pid)
    results.append(check("the_grandchild_did_not_survive_the_timeout", not alive,
                         f"pid {pid} still running"))
    return all(results)


def _text_of(exc) -> str:
    """A `TimeoutExpired`'s captured output as text, whichever it is."""
    if exc is None:
        return ""
    parts = []
    for value in (getattr(exc, "output", None), getattr(exc, "stderr", None)):
        if value is None:
            continue
        parts.append(value.decode("utf-8", "replace")
                     if isinstance(value, bytes) else str(value))
    return "".join(parts)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie is not running, but `kill(pid, 0)` still succeeds; its parent
    # (the killed build) is gone, so init reaps it — poll once more briefly.
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=10).stdout
        return bool(out.strip()) and "Z" not in out
    except Exception:  # noqa: BLE001
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.parse_args()
    with tempfile.TemporaryDirectory() as tmpdir:
        tests = [
            ("editing a hostmod source misses",
             lambda: test_editing_a_hostmod_source_misses(tmpdir)),
            ("whether a module resolves is in the key",
             lambda: test_whether_a_module_resolves_is_in_the_key(tmpdir)),
            ("a file with no imports is unaffected",
             lambda: test_a_file_with_no_imports_is_unaffected(tmpdir)),
            ("the sweep passes the digest",
             lambda: test_the_sweep_passes_the_digest(tmpdir)),
            ("the timeout takes the whole tree",
             lambda: test_the_timeout_takes_the_whole_tree(tmpdir)),
        ]
        failed = 0
        for name, fn in tests:
            print(f"── {name}")
            try:
                ok = fn()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL  {name}  {type(e).__name__}: {e}")
                ok = False
            if not ok:
                failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())