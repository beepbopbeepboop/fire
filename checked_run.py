#!/usr/bin/env python3
"""Deterministic-result cache for `make check`'s targets.

A check target (check-gimple, check-runner, check-modcache, check-selfhost)
is a pure function of its inputs: the compiler sources, the toolchain, and
whichever extra files it exercises (the test script itself, myinterpreter.py,
runtime sources, ...). Same hash of those inputs must always reproduce the
same outcome - once a hash has returned 0 it will always return 0, and once
it has returned some non-zero code it will always return that same code -
so the result is cacheable exactly like a compiled artifact. Reuses cas.py's
existing content-addressed store (same ~/.gmojo/cas directory, its own
'check/' key domain) instead of building a second cache mechanism.

One asymmetry, because the two cases are not equally safe to replay
(`--rerun-failures`, which tools/suite.py passes for every check):

- A cached **pass** is safe to replay. "This exact input set already compiled
  cleanly" stays true, and that is what makes `make check` fast on an
  unchanged tree.
- A cached **failure** is a claim about a past run, and the key only covers
  the files fed in with --extra. It cannot see the rest of what a check
  depends on: a stale build/ artifact, a filled disk, a module-cache
  directory left over from an interrupted run, the machine. Replaying one
  turns a red that may now be green into a permanent red that no amount of
  fixing will clear, which is strictly worse than spending the time to find
  out. So by default a failure is re-run and only its PASS is replayed. The
  cost is bounded: re-running a test that is genuinely broken is exactly what
  you would have done anyway.

Usage:
    python3 checked_run.py <name> [--extra path]... -- <command...>

`--extra` may name a DIRECTORY as well as a file, and a directory means every
file under it, recursively, hashed by relative path in sorted order. That is
the whole difference between an `extra` list that stays right and one that
rots: a test whose subject is a SET OF FILES - `formal/examples/*.mojo`, say -
cannot express that as a hand-kept list of 45 paths, because the 46th file is
added by someone who has no reason to know the list exists, and the list then
silently under-covers. Measured before this change: `--extra <dir>` hashed the
directory as one opaque name, so editing a file inside it did not move the key
and adding a file to it did not either. `examples-parse` guards 45 files that
way and is `cache=True`.

Naming each entry by its path RELATIVE TO THE DIRECTORY is what makes a RENAME
move the key, and a rename is what "a file was added and another removed" looks
like - exactly the change a hand-kept list misses, so a key that ignored it
would keep reporting a hit for a subject set that has changed shape.

A path that does not exist still hashes as a fixed marker, so a DELETED input
invalidates the key rather than silently revalidating it. That marker is
constant, so a path that never existed - a typo, or a glob nobody expanded -
leaves the key unmoved and caching quietly disabled for that test; `main` says
so on stderr when it happens, because the alternative is a cache that looks
like it is working and is not.

Exits with the cached (or freshly computed) command's exit code, after
replaying its stdout/stderr either way. Pass --no-cache to force a fresh run
(still publishes the result, so a subsequent normal invocation can hit it).
"""
import argparse
import json
import os
import subprocess
import sys

import cas
from build_config import find_gcc

GCC = find_gcc()

# A path that is not there hashes as this, so a DELETED input invalidates the
# key rather than revalidating it. Constant on purpose: see the docstring for
# why that is also the trap, and `main` for the warning that names it.
MISSING = b'\0missing'


def _hash_input(path: str, parts: list, missing: list) -> None:
    """Fold one `--extra` path into `parts`, and record it in `missing` if absent.

    A FILE contributes its path and its bytes. A DIRECTORY contributes every
    file under it, recursively, each named by the path it was given plus its
    path relative to that directory, so two different directories can never
    collide even when their contents are identical. `__pycache__` and `*.pyc`
    are skipped: they are derived from files already in the hash, and including
    them would make the key depend on whether the tree has been imported yet -
    the same class of "input" as a stale `build/`, which `tools/suite.py` is
    explicit that the key does not cover.

    The given path prefixes each entry rather than being dropped, for the same
    reason a file's path is hashed rather than just its bytes: the identity of
    an input is part of what the test depends on. `tools/suite.py` spells every
    `extra` entry repo-relative, so this costs nothing and moving the checkout
    does not invalidate anything in the store.
    """
    if os.path.isdir(path):
        base = os.path.abspath(path)
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames
                                 if d != '__pycache__' and not d.startswith('.'))
            for fn in sorted(filenames):
                if fn.endswith(('.pyc', '.pyo')):
                    continue
                full = os.path.join(dirpath, fn)
                found.append((os.path.relpath(full, base), full))
        if not found:
            missing.append((path, 'is an empty directory'))
            return
        for rel, full in sorted(found):
            parts += [path + '/' + rel.replace(os.sep, '/')]
            try:
                with open(full, 'rb') as f:
                    parts += [f.read()]
            except OSError:
                parts += [MISSING]
        return
    parts += [path]
    try:
        with open(path, 'rb') as f:
            parts += [f.read()]
    except OSError:
        parts += [MISSING]
        missing.append((path, 'does not exist'))


def check_key(name: str, extra_paths) -> str:
    parts = ['mojo-check-v1', name, cas.ABI_VERSION,
             cas.compiler_fingerprint(), cas.toolchain_fingerprint(GCC)]
    for p in sorted(extra_paths):
        _hash_input(p, parts, [])
    return 'check/' + cas.hash_parts(*parts)


def main():
    # argparse's REMAINDER handling gets confused when optionals (--extra)
    # are interspersed before it, so split on the literal '--' ourselves:
    # everything before it is our own flags, everything after is the command.
    argv = sys.argv[1:]
    if '--' in argv:
        sep = argv.index('--')
        own_args, cmd = argv[:sep], argv[sep + 1:]
    else:
        own_args, cmd = argv, []

    ap = argparse.ArgumentParser()
    ap.add_argument('name', help="check-target name, e.g. check-selfhost")
    ap.add_argument('--extra', action='append', default=[],
                     help="extra file whose content affects the outcome (repeatable)")
    ap.add_argument('--no-cache', action='store_true',
                     help="skip the cache read, but still publish the fresh result")
    ap.add_argument('--rerun-failures', action='store_true',
                     help="replay a cached PASS, but re-run a cached FAILURE "
                          "(see the module docstring: the key covers the files "
                          "passed with --extra, not the rest of the machine)")
    args = ap.parse_args(own_args)
    if not cmd:
        print("checked_run.py: no command given (pass it after --)", file=sys.stderr)
        sys.exit(2)

    key = check_key(args.name, args.extra)

    # Say so when an `--extra` path is not there. A missing path hashes to a
    # CONSTANT marker, so the key stops moving for that input and the test's
    # cached result is replayed for changes nobody can see. Nothing else in
    # the pipeline reports it: `tools/suite.py` replays this script's stderr
    # from the cache on a hit, but on a MISS - which is the first run, and the
    # run after the path is corrected - this is the only place it can appear.
    # Measured on this tree before it existed: zero specs had an unreadable
    # `extra` entry, so this is a trap rather than a live bug, which is exactly
    # why it is cheap to say and expensive to discover later.
    for p in args.extra:
        if not os.path.exists(p):
            print(f"[checked_run] {args.name}: --extra {p!r} does not exist. "
                  f"Its content is hashed as a fixed marker, so this test's "
                  f"cached PASS will be replayed for any change to it. If it "
                  f"is a glob, expand it; if it is a directory of inputs, name "
                  f"the directory (a directory is hashed by its contents).",
                  file=sys.stderr)

    if not args.no_cache:
        cached = cas.lookup(key, '.json')
        if cached:
            with open(cached) as f:
                result = json.load(f)
            stale = args.rerun_failures and result['returncode'] != 0
            if not stale:
                sys.stdout.write(result['stdout'])
                sys.stderr.write(result['stderr'])
                print(f"[checked_run] {args.name}: cached result replayed "
                      f"(unchanged inputs, key {key[7:19]}...)", file=sys.stderr)
                sys.exit(result['returncode'])
            print(f"[checked_run] {args.name}: cached result was a FAILURE "
                  f"(exit {result['returncode']}, key {key[7:19]}...) — "
                  f"re-running it: a failure is a claim about a past run, and "
                  f"the key covers the --extra files, not the state of the "
                  f"machine.", file=sys.stderr)

    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    cas.publish(key, '.json', json.dumps({
        'returncode': proc.returncode,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
    }).encode('utf-8'))
    sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
