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

Exits with the cached (or freshly computed) command's exit code, after
replaying its stdout/stderr either way. Pass --no-cache to force a fresh run
(still publishes the result, so a subsequent normal invocation can hit it).
"""
import argparse
import json
import subprocess
import sys

import cas
from build_config import find_gcc

GCC = find_gcc()


def check_key(name: str, extra_paths) -> str:
    parts = ['mojo-check-v1', name, cas.ABI_VERSION,
             cas.compiler_fingerprint(), cas.toolchain_fingerprint(GCC)]
    for p in sorted(extra_paths):
        try:
            with open(p, 'rb') as f:
                parts += [p, f.read()]
        except OSError:
            parts += [p, b'\0missing']
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
