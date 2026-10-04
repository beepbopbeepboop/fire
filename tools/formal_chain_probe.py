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
3. replaces one refusing module — the first in sorted-path order that names a
   file this tool may rewrite, so the walk is deterministic — in a THROWAWAY COPY
   of the stdlib with a stub that exports one function, and drops the import
   lines naming it, so its re-exports stop being what the next round reports;
4. asks again.

WHICH MODULE REFUSED
--------------------
Two shapes, and the SECOND one is why a round could report zero links on a scope
whose largest group was 37 of 46 files (measured 2026-10-04 on
`std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}`, `work/formal20-std-os-io-2`):

  · formal/build.py's chain wrapper, `<file>: <that file's own error>` — the
    prefix names the refusing file directly.
  · `formal/model.py::imported_callee_refusal`, which is what a call to a name
    the DEFINING module does not export produces, and which names the module in
    PROSE (`... it is imported from `std.format._utils`, so the call has to bind
    a symbol `std.format._utils` exports`) rather than in that prefix. It is
    also the single largest cause in the tree: 123 files, per
    `bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
    §1.

That second shape used to fall into the catch-all `<no module named>` group,
whose key is not a filename, so step 3 had nothing to rewrite and the walk
stopped at round 0 — reporting *no chain at all* for the refusal that blocks the
most files. It is resolved with the build's OWN resolver,
`formal.imports.resolve_module_path(name, relative_to=importer)`, rather than by
a second spelling rule here: that one already knows a dotted name
(`std.format._utils`), a package (`std.math` → `std/math/__init__.mojo`) and a
relative spelling (`..fstat`, `.path`) resolve, and it is the resolver the builds
that produced these messages used. A name it cannot resolve stays unrewritable,
and step 3 then says so in words instead of trying to rewrite a placeholder.

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

# The group key for a refusal that names no module at all. NOT a filename, and
# that is the whole reason `stub_targets` refuses it: this tool rewrites files
# inside the copy and there is nothing here to rewrite.
NO_MODULE = "<no module named>"

# formal/build.py's chain wrapper: `<file>: <that file's own error>`.
_CHAIN_PREFIX_RE = re.compile(r"([\w./]+\.mojo): ")

# formal/model.py::imported_callee_refusal, which names the DEFINING module in
# prose instead.  The backtick span is the module name as the resolver spells it
# — `std.format._utils`, `std.math`, `..fstat`, `.path`.
_EXPORT_GATE_RE = re.compile(r"is imported from `([^`]+)`")


def _resolve_module(name, importer):
    """Where the build's own resolver puts module `name`, or None.

    `formal.imports.resolve_module_path` rather than a path rule written here,
    because it is the resolver the builds that produced these messages used: it
    knows that `std.math` is `std/math/__init__.mojo` and that `..fstat` is
    relative to the importing FILE, and a second spelling rule in this tool
    would be a second thing to keep right. None on any failure — an unresolvable
    name leaves its group unrewritable, which is the honest outcome and not a
    reason to guess a path.
    """
    if not name or not importer:
        return None
    try:
        from formal.imports import resolve_module_path
        found = resolve_module_path(name, relative_to=str(importer))
    except Exception:
        return None
    return pathlib.Path(found).resolve() if found else None


def refusing_module(msg, importer, rel):
    """Which module refused, as `(group key, exact file or None, stem)`.

    `exact` is the one file to rewrite when the resolver could place the module;
    None means the key is a bare basename and `stub_targets` falls back to
    searching the copy for it, which is what a chain-prefix refusal has always
    done and what a basename like `stat.mojo` (both a stdlib package and a
    hostmod) needs. `stem` is the bare module name for the import-line drop in
    either case: `from std.math import align_up` and `from ..fstat import stat`
    both name their module by its last component.

    `rel` renders a path relative to the copy, for the printed group key and the
    example line, so a reader sees `std/format/_utils.mojo` rather than an
    absolute path under `.tmp`.
    """
    chain = _CHAIN_PREFIX_RE.findall(msg)
    if chain:
        base = chain[-1]
        return base, None, base[:-len(".mojo")]
    m = _EXPORT_GATE_RE.search(msg)
    if not m:
        return NO_MODULE, None, ""
    name = m.group(1)
    stem = name.rsplit(".", 1)[-1]
    exact = _resolve_module(name, importer)
    if exact is None:
        return name, None, stem
    return rel(exact) or str(exact), exact, stem


def stub_targets(group, probe):
    """The files to replace for `group`, and [] when there are none.

    An `exact` file is the only target: it is placed by the resolver, so a
    package whose stem is `__init__` rewrites exactly the one package the walk
    stopped at instead of every `__init__.mojo` in the copy.
    """
    exact = group["exact"]
    if exact is not None:
        return [exact] if exact.is_file() else []
    stem = group["stem"]
    if not stem:
        return []
    return sorted(probe.rglob(stem + ".mojo"))


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
        groups = {}
        built = []
        for path, rc, msg in rows:
            if rc == 0:
                built.append(path)
                continue
            if rc is not None and "the backend raised" in msg:
                crashed.append((path, msg))
                continue
            key, exact, stem = refusing_module(
                msg, path, lambda p: under_stdlib(p, probe))
            group = groups.get(key)
            if group is None:
                # First answer wins the placement. Two files in the same scope
                # can name the same module in two spellings that resolve
                # differently only if the resolver disagrees with itself, and
                # the walk must be deterministic, so it does not get a vote.
                group = groups[key] = {"exact": exact, "stem": stem,
                                       "members": []}
            group["members"].append((path, msg))
        print(f"\n=== round {rnd}: {len(built)} built, "
              f"{len(groups)} refusing module(s)")
        for mod in sorted(groups, key=lambda k: (-len(groups[k]["members"]), k)):
            members = groups[mod]["members"]
            path, msg = members[0]
            rel = under_stdlib(path, probe) or str(path)
            print(f"  {len(members):3d}  {mod}")
            print(f"       example: {rel}")
            print(f"       {msg[:300]}")
        if not groups:
            break
        # The first group in sorted-path order THAT NAMES A FILE THIS TOOL MAY
        # REWRITE. Sorting the groups first and taking [0] unconditionally is
        # what made a round with a catch-all group stop at round 0 with a
        # placeholder sliced as if it were a filename.
        victim = next((k for k in sorted(groups)
                       if stub_targets(groups[k], probe)), None)
        if victim is None:
            unrewritable = ", ".join(sorted(groups))
            print(f"\n  (stopping: none of the refusing groups names a file in "
                  f"the stdlib copy this tool may rewrite — {unrewritable})")
            break
        stubbed = stub_targets(groups[victim], probe)
        stem = groups[victim]["stem"]
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
