#!/usr/bin/env python3
"""How DEEP is a sweep scope's refusal chain, and what is each link?

`tools/formal_sweep.py` reports one link per file: the terminal refusal its
build walk reaches, so a file blocked five modules down prints the same class
and nearly the same sentence as one blocked one module down. That is the right
answer to "what is the FIRST thing this file cannot build" and the wrong answer
to "what is wrong with this file", and the sweep's own work map says so in one
line — *"FILES BLOCKED IS AN UPPER BOUND: a file's terminal cause is the first
refusal its build walk reaches, so fixing one moves the file to the next with the
count unchanged"* (`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3). This tool
measures the rest of the chain, one link per round.

WHAT IT DOES, per round
----------------------
1. asks every path for its terminal refusal, by running the same
   `fire.py build --formal --no-prove` the sweep runs;
2. groups the answers by the module that refused, and prints the count, one
   example file and the message for each group;
3. replaces one refusing module — the first in sorted-path order, so the walk is
   deterministic — in a THROWAWAY COPY of the stdlib with a stub that exports one
   function, and drops the import lines naming it, so its re-exports stop being
   what the next round reports;
4. asks again.

THE LIMIT, stated in the output rather than only here, because it decides what
the numbers mean
------------------------------------------------------------------------
Neutering a module removes the names its **users** call, so past the first link
or two a round can be measuring what the module just stubbed was used for rather
than the next link in the chain. The tell is a group's count moving when a
DIFFERENT group was stubbed, and `round N:` prints every group, so a reader sees
it. Links measured before that starts are the ones worth acting on.

THE STDLIB IS ONLY EVER READ
----------------------------
The copy is under `.tmp/chain-probe` and is rewritten every run; the real
`../new-modular/Mojo/stdlib` is never written to. `MOJO_STDLIB` points the copy
for the builds, which is the same switch `module_loader.py` reads, so the chain
is walked against a stdlib and not against a mixture of two.

    python3 tools/memslot.py --gb 8 --label chain -- \
        python3 tools/formal_chain_probe.py 9 arm64 \
        ../new-modular/Mojo/stdlib/std/os \
        ../new-modular/Mojo/stdlib/std/sys

Exit 0 unless a build CRASHED the backend, which is a finding about this tree
rather than about the chain (`formal_sweep.py`'s own `backend-crash` class), and
which is reported per path.
"""

import argparse
import collections
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
FIRE = str(HERE / "fire.py")
DEFAULT_ROUNDS = 9
BUILD_TIMEOUT = 120


def stdlib_files(roots):
    """Every `.mojo` under `roots`, sorted, as absolute paths."""
    out = []
    for root in roots:
        p = pathlib.Path(root)
        if p.is_file():
            out.append(p.resolve())
        elif p.is_dir():
            out += sorted(q.resolve() for q in p.rglob("*.mojo"))
        else:
            raise SystemExit(f"no such path: {root}")
    return out


def under_stdlib(path, stdlib):
    """`path` relative to `stdlib`, or None when it is not under it.

    Only files inside the copy can be rewritten, so a round that stubs a module
    has to be able to name it; a scope file that lives outside the stdlib (this
    repository's own `*.py`) is measured but never rewritten, which is why the
    stub step says so when it happens.
    """
    try:
        return str(path.relative_to(stdlib))
    except ValueError:
        return None


def build(path, out, arch, env):
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            f"--backend={arch}", "-o", str(out), str(path)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {BUILD_TIMEOUT}s"
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def round_messages(paths, outdir, arch, env):
    """`{path: first `build:` line}` for one round, in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    def one(path):
        rc, text = build(path, outdir / (str(path).replace("/", "_") + ".bin"),
                         arch, env)
        line = next((l for l in (text or "").splitlines()
                     if l.startswith("build:")), "")
        return path, rc, (line or (text or "").strip())[:400]

    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(one, paths))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rounds", nargs="?", type=int, default=DEFAULT_ROUNDS,
                    help=f"links to walk (default {DEFAULT_ROUNDS})")
    ap.add_argument("arch", nargs="?", default="arm64",
                    help="machine subset (default arm64)")
    ap.add_argument("--stdlib", default=None, metavar="PATH",
                    help="stdlib root to copy and rewrite (default: the "
                         "checkout module_loader finds, i.e. MOJO_STDLIB or "
                         "../new-modular/Mojo/stdlib)")
    ap.add_argument("paths", nargs="*",
                    help="files or directories to measure (default: this "
                         "repository's own *.py and *.mojo)")
    args = ap.parse_args()

    stdlib = pathlib.Path(args.stdlib or os.environ.get("MOJO_STDLIB")
                          or (HERE.parent / "new-modular" / "Mojo"
                              / "stdlib")).resolve()
    if not stdlib.is_dir():
        raise SystemExit(f"no stdlib at {stdlib}; pass --stdlib PATH")

    probe = (HERE / ".tmp" / "chain-probe").resolve()
    shutil.rmtree(probe, ignore_errors=True)
    shutil.copytree(stdlib, probe)
    outdir = (HERE / ".tmp" / "chain-out").resolve()
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)

    roots = args.paths or [str(HERE)]
    scope = stdlib_files(roots)
    # A path given inside the REAL stdlib is measured against the COPY, so every
    # answer comes from the same tree and a stub can take effect. A path outside
    # it (this repository's own `*.py`) is measured against itself and is never
    # rewritten — the stub step says so rather than pretending otherwise.
    scope = [probe / under_stdlib(p, stdlib) if under_stdlib(p, stdlib) else p
             for p in scope]
    env = dict(os.environ, MOJO_STDLIB=str(probe))

    print(f"stdlib copy: {probe}")
    print(f"scope: {len(scope)} file(s); {args.rounds} round(s) on "
          f"{args.arch}")
    crashed = []
    for rnd in range(args.rounds):
        rows = round_messages(scope, outdir, args.arch, env)
        groups = collections.defaultdict(list)
        built = []
        for path, rc, msg in rows:
            if rc == 0:
                built.append(path)
                continue
            if rc is not None and "the backend raised" in msg:
                crashed.append((path, msg))
                continue
            hits = re.findall(r"([\w./]+\.mojo): ", msg)
            groups[hits[-1] if hits else "<no module named>"].append(
                (path, msg))
        print(f"\n=== round {rnd}: {len(built)} built, "
              f"{len(groups)} refusing module(s)")
        for mod in sorted(groups, key=lambda k: (-len(groups[k]), k)):
            members = groups[mod]
            path, msg = members[0]
            rel = under_stdlib(path, probe) or str(path)
            print(f"  {len(members):3d}  {mod}")
            print(f"       example: {rel}")
            print(f"       {msg[:300]}")
        if not groups:
            break
        victim = sorted(groups)[0]
        stem = victim[:-len(".mojo")]
        stubbed = list(probe.rglob(stem + ".mojo"))
        if not stubbed:
            print(f"\n  (stopping: {stem} is not under the stdlib copy, so "
                  f"there is nothing this tool may rewrite)")
            break
        for p in stubbed:
            p.write_text(
                f'"""{p.name}, stubbed by tools/formal_chain_probe.py."""\n\n'
                f"def chain_probe_{re.sub(r'[^A-Za-z0-9]', '_', stem)}"
                f"(x: Int) -> Int:\n    return x\n")
        pat = re.compile(r"^\s*(from|import)\s+[\w.]*\b" + re.escape(stem)
                         + r"\b.*$")
        dropped = 0
        for p in probe.rglob("*.mojo"):
            lines = p.read_text().split("\n")
            keep = [l for l in lines if not pat.match(l)]
            if len(keep) != len(lines):
                p.write_text("\n".join(keep))
                dropped += 1
        print(f"  stubbed {victim} ({len(stubbed)} file(s)) and dropped "
              f"import lines from {dropped} file(s); next round")

    for path, msg in crashed:
        print(f"BACKEND-CRASH: {path}  (the backend raised, which is a finding "
              f"about this tree rather than about the chain)\n    {msg[:300]}")
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
