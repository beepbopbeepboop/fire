#!/usr/bin/env python3
"""Every `formal/hostmods` module, built as a PROGRAM, on BOTH backends.

    python3 test_formal_hostmods_census.py [-v] [module ...]

## Why this file exists

Every host module except `argparse` used to be assumed buildable on the strength
of its own test file, and nothing ever asked the question directly.  That is a
quiet kind of hole: a module that does not build is not a red anywhere, it is an
*unbuildable dependency*, so every program importing it is refused for a
diagnostic whose subject is a line inside a file the reader never opened — 36 of
argparse's 44 sweep rows carried one message about a comparison in `_lookup`,
and not one of the 36 had anything to do with `_lookup`.

So this is the cheapest possible early warning: the module as a translation unit,
with nothing importing it, once per architecture.  The whole table is 16 modules
x 2 backends and it costs about 15 seconds.

## What is asserted, and why it is not a snapshot

A recorded table of every verdict would be wrong within a week — every row is a
moving target, and a red that says "the census moved" is a red nobody acts on.
So the assertions are the two PROPERTIES the table has to have, and the table
itself is printed:

  1. **Every module builds on arm64.**  arm64 is the corpus backend, and a host
     module that does not lower there is a hole in the language this tree
     implements.  There is no exemption on this side and there never should be.
  2. **x86-64 is a SUBSET of arm64.**  A module that builds on x86-64 and not on
     arm64 is a two-architecture divergence, which is the one thing two
     architectures of one language implementation may not do — and it is the
     failure mode that a per-backend test cannot see, because the backend under
     test is the one that changed.

Property 3 is `KNOWN_X86_64_ONLY`, the repo's `expect=` discipline applied to a
census: a module that refuses on x86-64 and not on arm64 is recorded there with
the words it has to refuse with and the filing that owns it, and **a refusal
that is not recorded there fails the census**.  It is EMPTY today, which is the
point of the table — it held `fnmatch.mojo` and `pathlib.mojo` until both
ABIs grew a stack-argument convention, and the check that caught them going
green was itself removed with its last row, because a check over no rows is not
a check.

## Why a COLD CAS per row

A module dylib is cached by content, so a verdict from a previous version of the
file would answer the wrong question — which is the measurement in
`bugs/FORMAL_cas_verdict_key_ignores_the_hostmod_sources_it_compiles.md`, and it
is the reason this file points `GMOJO_HOME` at a private directory per row
rather than sharing one.  It is also why the build is not deduplicated across
rows: `os/__init__.mojo` and `os/path/__init__.mojo` both import
`os/_syscalls.mojo`, and sharing a CAS between them would let the first row's
library answer for the second row's source.

    python3 test_formal_hostmods_census.py --list
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTMODS = os.path.join(HERE, "formal", "hostmods")

sys.path.insert(0, HERE)

# The independent driver and the assertion helper live in the dylib suite;
# imported rather than copied so a fix to either cannot leave a second, quietly
# different one behind — the same reason `test_formal_argparse.py` does this.
from test_formal_dylib import (TestFailure, check, run_fire)  # noqa: E402

BACKENDS = ("arm64", "x86_64")


def hostmod_modules():
    """Every `formal/hostmods` module, as a path relative to `hostmods/`.

    Walked rather than listed, so a module added to the tree is IN this file's
    subject the moment it lands.  A hand-maintained list is a list that is wrong
    the day somebody adds `platform.mojo`, and the whole value of a census is
    that it cannot be.
    """
    out = []
    for dirpath, dirs, files in os.walk(HOSTMODS):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".mojo"):
                full = os.path.join(dirpath, name)
                out.append((os.path.relpath(full, HOSTMODS), full))
    return sorted(out)


# The x86-64 rows that are KNOWN not to build, each with the words the build has
# to refuse with and the filing that owns it.
#
# IT IS EMPTY, and it was not: it held `fnmatch.mojo` and `pathlib.mojo`, both
# refused because SysV x86-64 passed six integer arguments in registers and had
# no stack area, so `match_core(7)` had nowhere to go.  Both conventions have
# one now (`formal/x86_64_codegen.py`'s `_load_home_from_stack` and `_emit_call`
# on x86-64, `_MAX_INCOMING_ARGS` on both), which is what
# `bugs/FORMAL_x86_64_argument_registers.md` asked for (that filing is deleted
# too, with its emitters half landed), so the rows are deleted
# rather than re-needleed.
#
# `test_known_x86_64_failures_are_still_failing` went with them.  It existed to
# make a row here a claim about TODAY — a row that BUILDS is a failure, exactly
# as `tools/suite.py` reports an `expect=`-marked test that starts passing — and
# a table with no rows has nothing for it to check.  `test_no_unrecorded_x86_64_
# failures` is the half that stays meaningful with an empty table and is the
# reason the deletion is safe: a refusal that is NOT recorded here fails the
# census, so the next x86-64-only gap has to arrive with a row rather than
# quietly.
#
# The two rows are named in that commit because a census row is a per-module
# build and this table is the only place the shape of the loss was written down:
# `pathlib` was listed SEPARATELY from `fnmatch`, with the importer in the
# needle, because its refusal was chained — it imports `fnmatch`, so its own body
# was never reached, and one row saying "pathlib fails" would have been true for
# a week after fnmatch was fixed and then quietly untrue.
KNOWN_X86_64_ONLY: dict = {}


def build_module(path, backend, tmpdir, cas_root):
    """`fire.py build --formal` of one module, on a CAS of its own.

    The private `GMOJO_HOME` is the point: a module dylib is cached by content
    and a shared CAS would let a row's own library answer for a later row.
    """
    home = os.path.join(cas_root, backend, os.path.basename(path))
    os.makedirs(home, exist_ok=True)
    out = os.path.join(tmpdir, f"{backend}-{os.path.basename(path)}.aout")
    r = run_fire(["build", "--formal", "--no-prove", f"--backend={backend}",
                  "-o", out, path],
                 env={"GMOJO_HOME": home})
    return r, out


def verdict(r, out):
    """`BUILD`, or the first line of the refusal."""
    if r.returncode == 0 and os.path.isfile(out):
        return "BUILD"
    if r.returncode == 0:
        return "BUILT BUT WROTE NO IMAGE"
    text = (r.stderr or r.stdout or "").strip()
    return text.splitlines()[0] if text else f"exit {r.returncode} with no output"


def census(selected):
    """(module, backend) -> verdict, for every row."""
    rows = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        cas_root = tempfile.mkdtemp(prefix="hostmods_census_",
                                    dir=os.environ.get("TMPDIR") or None)
        try:
            for rel, full in hostmod_modules():
                if selected and rel not in selected:
                    continue
                for backend in BACKENDS:
                    r, out = build_module(full, backend, tmpdir, cas_root)
                    rows[(rel, backend)] = (verdict(r, out), r)
        finally:
            shutil.rmtree(cas_root, ignore_errors=True)
    return rows


def print_table(rows):
    """The census, as a table — the artifact the filing was.

    Printed whatever the run's verdict is, because a census whose table only
    appears when something failed is a census that has already lost the thing it
    was for.
    """
    mods = sorted({rel for rel, _b in rows})
    width = max((len(m) for m in mods), default=4)
    print(f"  {'module'.ljust(width)}  " + "  ".join(b.ljust(10)
                                                     for b in BACKENDS))
    for m in mods:
        cells = []
        for b in BACKENDS:
            v = rows.get((m, b), ("-", None))[0]
            cells.append(("BUILD" if v == "BUILD" else v[:38]).ljust(10))
        print(f"  {m.ljust(width)}  " + "  ".join(cells))


def test_every_hostmod_builds(rows):
    """Property 1: every module lowers on arm64, with no exemption."""
    bad = []
    for (rel, backend), (v, _r) in sorted(rows.items()):
        if backend != "arm64":
            continue
        if v != "BUILD":
            bad.append(f"{rel}: {v}")
    check(not bad,
          "every host module must build on arm64, and these do not.  arm64 is "
          "the corpus backend, so a module that does not lower there is a hole "
          "in the language rather than a backend gap, and it makes every "
          "program that imports it unbuildable with a diagnostic whose subject "
          "is a line inside this file:\n    " + "\n    ".join(bad))


def test_x86_64_is_a_subset_of_arm64(rows):
    """Property 2: nothing builds on x86-64 that does not build on arm64.

    The direction a per-backend test structurally cannot see, because the
    backend under test is the one that changed.  A module that lowered on x86-64
    and was refused on arm64 is a two-architecture divergence, and which
    architecture is right is a question this file deliberately does not answer —
    it reports the disagreement and leaves the answer to whoever owns the
    emitter.
    """
    bad = []
    for (rel, backend), (v, _r) in sorted(rows.items()):
        if backend != "x86_64" or v != "BUILD":
            continue
        arm = rows.get((rel, "arm64"), ("-", None))[0]
        if arm != "BUILD":
            bad.append(f"{rel}: x86_64 BUILD, arm64 {arm}")
    check(not bad,
          "a module built on x86-64 but not on arm64 is a two-architecture "
          "divergence:\n    " + "\n    ".join(bad))


def test_no_unrecorded_x86_64_failures(rows):
    """Property 1's mirror on x86-64: an unrecorded refusal is a FAILURE.

    This is what makes `KNOWN_X86_64_ONLY` a claim about the present rather than
    a wish, and it is the assertion that would have caught the two rows the
    filing recorded: `os/_syscalls.mojo` failing to LINK on x86-64 made four
    rows `FAIL (import)`, and all four said so about a module that was fine.
    """
    bad = []
    for (rel, backend), (v, _r) in sorted(rows.items()):
        if backend != "x86_64" or v == "BUILD":
            continue
        if rel in KNOWN_X86_64_ONLY:
            continue
        bad.append(f"{rel}: {v}")
    check(not bad,
          "these refuse on x86-64 without a row in KNOWN_X86_64_ONLY saying so.  "
          "A known failure is one anybody recorded; an unrecorded one is a new "
          "finding, and the recording is the fix — add the row with the needle "
          "and the filing that owns it:\n    " + "\n    ".join(bad))


TESTS = [
    ("every hostmod builds on arm64", test_every_hostmod_builds),
    ("x86-64 is a subset of arm64", test_x86_64_is_a_subset_of_arm64),
    ("no unrecorded x86-64 failure", test_no_unrecorded_x86_64_failures),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true",
                    help="list the modules and the known x86-64 rows, and exit")
    ap.add_argument("modules", nargs="*",
                    help="run only these (paths relative to formal/hostmods)")
    args = ap.parse_args()

    mods = hostmod_modules()
    if args.list:
        for rel, _full in mods:
            note = ""
            if rel in KNOWN_X86_64_ONLY:
                needle, why = KNOWN_X86_64_ONLY[rel]
                note = f"   [x86-64: {needle[:44]}... — {why}]"
            print(f"  {rel}{note}")
        print(f"\n  {len(mods)} modules x {len(BACKENDS)} backends; "
              f"{len(KNOWN_X86_64_ONLY)} recorded x86-64 failure(s)")
        return 0

    if platform.machine() not in ("arm64", "aarch64"):
        # Not a skip of the subject: the census builds for an explicit
        # `--backend`, so it works from either host.  What does not work is
        # RUNNING the result, and this file never runs it — it asks whether a
        # module lowers.  So there is nothing here to refuse.
        print(f"note: host is {platform.machine()}; both backends are built "
              f"explicitly and nothing is executed")

    rows = census(args.modules)
    print_table(rows)
    if args.verbose:
        for (rel, backend), (v, _r) in sorted(rows.items()):
            print(f"      {rel} [{backend}] {v}")

    passed = failed = 0
    for name, fn in TESTS:
        try:
            fn(rows)
        except TestFailure as e:
            failed += 1
            print(f"  FAIL  {name}\n        {e}")
            continue
        except Exception as e:              # unexpected: report, do not mask
            failed += 1
            print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            continue
        passed += 1
        print(f"  PASS  {name}")

    built = sum(1 for v, _r in rows.values() if v == "BUILD")
    print(f"\nformal hostmods census: PASS={passed} FAIL={failed}  "
          f"({built}/{len(rows)} rows build)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
