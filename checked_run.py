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
    python3 checked_run.py <name> [--extra path]... [--extra-glob pat]... -- <command...>

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

A directory covers a set that LIVES somewhere. A set that is FLAT has no such
directory, and the only other way to name it is the hand-kept list that just
rotted: the repo's own `test_*.py` is 93 files in one directory, which is the
subject of the estate check inside `test_suite.py`. So `--extra-glob` takes a
shell pattern, expands it against the CWD, and folds in every match. It is a
separate flag rather than a pattern `--extra` might also be read as, because
silently reinterpreting an existing argument is invisible until it is wrong.

A glob recurses where a named directory did not have to, so it also needs the
skip rule a named directory does not: `**/test_*.py` reaches `build/`, and the
A/B machinery's `aside/` and `bside/` hold COPIES of repo files under a second
name. Those are not inputs, and folding them in would make the key depend on
whether a sweep had run. `DERIVED_DIRS` is that rule, read by both walks here
and by `test_suite.py`'s own subject walk, because two copies of a directory
list is one copy too many.

That is not a hypothetical there. `suite-self-test` is `cache=True` and carries
the estate check, which is the check that fails when a test file lands with
neither a registration nor a reason. Keyed on the runner's own sources, adding
`test_whatever.py` moved nothing: a recorded PASS was replayed and the check
written to catch exactly that never ran. A guard behind a cache whose key
cannot see its own subject is not a guard.

Naming each entry by its path RELATIVE TO THE DIRECTORY is what makes a RENAME
move the key, and a rename is what "a file was added and another removed" looks
like - exactly the change a hand-kept list misses, so a key that ignored it
would keep reporting a hit for a subject set that has changed shape.

A path that does not exist still hashes as a fixed marker, so a DELETED input
invalidates the key rather than silently revalidating it. That marker is
constant, so a path that never existed - a typo, or a glob nobody expanded -
leaves the key unmoved and caching quietly disabled for that test; `main` says
so on stderr when it happens, because the alternative is a cache that looks
like it is working and is not. A `--extra-glob` that matches NOTHING is the
same trap wearing a louder hat, and says so in its own words: an expanded set
that came back empty is either a pattern nobody meant or a subject that has
gone, and either way the key has to stop moving.

Exits with the cached (or freshly computed) command's exit code, after
replaying its stdout/stderr either way. Pass --no-cache to force a fresh run
(still publishes the result, so a subsequent normal invocation can hit it).
"""
import argparse
import glob
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

# Directory names whose contents are not an input to anything. ONE list, read
# by both callers that walk a tree, because the second one is here: `_hash_input`
# had `__pycache__` and dot-directories hard-coded in its own walk, and a glob
# needs the same rule plus three more names — and a rule written twice is a
# rule whose two copies have already drifted once (they did).
#
#   __pycache__  derived from files already in the hash, so including it makes
#                the key depend on whether the tree has been imported yet
#   build/       this project's derived output (`tools/suite.py` is explicit
#                that the key does not cover a stale `build/`)
#   aside/ bside/  the A/B machinery's per-file COPIES of repo files — the same
#                content under a second name, which would double every input and
#                make the key depend on a sweep having run
#
# A leading `.` is skipped on the same grounds as all of them (VCS metadata,
# tool caches). It is a predicate rather than a set membership test because
# `.git` and `.tmp` have to go without anyone remembering to add them.
DERIVED_DIRS = frozenset({'__pycache__', 'build', 'aside', 'bside'})


def is_derived_dir(name: str) -> bool:
    """Whether a directory NAME is one whose contents are not an input."""
    return name in DERIVED_DIRS or name.startswith('.')


def _hash_input(path: str, parts: list, missing: list) -> None:
    """Fold one `--extra` path into `parts`, and record it in `missing` if absent.

    A FILE contributes its path and its bytes. A DIRECTORY contributes every
    file under it, recursively, each named by the path it was given plus its
    path relative to that directory, so two different directories can never
    collide even when their contents are identical. `DERIVED_DIRS` is skipped,
    for the reasons documented there.

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
            dirnames[:] = sorted(d for d in dirnames if not is_derived_dir(d))
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


def expand_globs(patterns) -> tuple:
    """`(paths, empty_patterns)` for a list of `--extra-glob` patterns.

    Sorted, and a path matched by two patterns comes back once: the key is
    built from the SET of files, and listing one twice because two patterns
    overlap would make the key depend on the overlap rather than on the
    subject. `recursive=True` so `**/…` is available for a flat pattern whose
    set has since grown a subdirectory — which is exactly how this suite's own
    subject set would rot if the pattern were pinned to the top level. A `**`
    pattern matches the top level too, so `**/test_*.py` covers both the repo's
    root and its subdirectories with one pattern rather than a list per depth.

    A hit under a `DERIVED_DIRS` directory is DROPPED, and this is the one
    place a glob needs a rule a named `--extra <dir>` does not. An author who
    writes `--extra formal/examples` has chosen that directory and means all of
    it; an author who writes `--extra-glob '**/test_*.py'` has said "everything
    shaped like this anywhere under the checkout", and `build/`, `aside/` and
    `bside/` are shaped like it while being derived, duplicated or stale. Left
    in, the key would depend on whether an A/B sweep or a build had run — the
    same "input" the module docstring refuses for `__pycache__`, arrived at by
    the other route.

    …and the rule is applied to the components the PATTERN decides, not to the
    whole path, which is the difference between a rule and a veto. `**/…`
    decides every component below the directory it is anchored at, so it cannot
    reach into `build/`; `/src/build/x_*.py` decides only `x_*.py`, because the
    author wrote `build` themselves and meant it. Without that distinction the
    rule misfires on innocent paths — this repo's `TMPDIR` is `.tmp/` inside the
    checkout, so an absolute pattern under it dropped every hit, and a test
    written to prove the rule works would have proved the opposite.

    A pattern that matches nothing comes back in the second list rather than
    being folded in as a missing path. It is a different failure from a
    mistyped `--extra`: the pattern parsed, it was expanded, and the set it
    named is empty, which is either a subject that has gone or a pattern that
    does not spell what its author thought. `main` says which.
    """
    found, empty = set(), []
    for pat in patterns:
        pinned = _pinned_prefix_len(pat)
        hits = sorted(h for h in glob.glob(pat, recursive=True)
                      if not _under_derived_dir(h, pinned))
        if not hits:
            empty.append(pat)
        found.update(hits)
    return sorted(found), empty


def _pinned_prefix_len(pattern: str) -> int:
    """How many leading components of `pattern` are literal.

    Everything up to the first component carrying a wildcard, which is exactly
    the part of the path the glob cannot decide: `**/test_*.py` pins nothing
    (the first component IS a wildcard) and `/src/build/x_*.py` pins three.
    `expand_globs` skips this many components of each match before asking
    whether the rest reaches a derived directory.
    """
    pinned = 0
    for comp in os.path.normpath(pattern).split(os.sep):
        if any(ch in comp for ch in '*?['):
            break
        if comp:
            pinned += 1
    return pinned


def _under_derived_dir(path: str, skip: int = 0) -> bool:
    """Whether a component of `path` past the first `skip` is a directory whose
    contents are not an input.

    The components of the path as written, not of its absolute form: `glob`
    yields matches in the shape of the pattern, and an answer that depended on
    the caller's cwd would drop files for a reason that has nothing to do with
    them.
    """
    parts = [p for p in os.path.normpath(path).split(os.sep) if p]
    return any(is_derived_dir(p) for p in parts[skip:])


def check_key(name: str, extra_paths, glob_patterns=()) -> str:
    """The cache key: a function of the SET of input files, and of nothing else.

    The patterns are expanded HERE rather than by the caller, and that is not
    tidiness. `check_key(name, [], ['test_*.py'])` reads as "the files matching
    this", and if the function instead treated the string as a path it hashed
    as a constant missing marker and the key never moved — a cache that is
    silently blind to its whole subject, from a call that looks correct. There
    is one place that knows patterns are patterns, and this is it.

    Deduplicated across both lists for the same reason: a file named by
    `extra` and matched by a glob is one input, and hashing it twice would make
    the key depend on the overlap between the two lists rather than on the
    subject. (`gimplerunner` names `gimple_codegen.py` on top of the
    `GIMPLE_SOURCES` list that already has it, so this is not hypothetical: that
    spec's key moves once, which is a cache miss and nothing else.)
    """
    globbed, _empty = expand_globs(glob_patterns)
    inputs = sorted(set(extra_paths) | set(globbed))
    parts = ['mojo-check-v1', name, cas.ABI_VERSION,
             cas.compiler_fingerprint(), cas.toolchain_fingerprint(GCC)]
    for p in inputs:
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
    ap.add_argument('--extra-glob', action='append', default=[],
                     help="shell pattern naming a SET of inputs to hash, for a "
                          "subject that is not one file and not one directory "
                          "(repeatable; a pattern matching nothing is reported)")
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

    # The empty-pattern list is worked out here as well as inside `check_key`,
    # which is a second expansion of the same patterns. It costs one listdir:
    # `check_key` owns the expansion so that no caller can hand it a pattern it
    # will hash as a path, and this line is here only because the warning below
    # is a separate concern from the key. One function knows patterns are
    # patterns; asking it twice is cheaper than a second way to get it wrong.
    empty_globs = expand_globs(args.extra_glob)[1]
    key = check_key(args.name, args.extra, args.extra_glob)

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
                  f"cached PASS will be replayed for any change to it. If it is "
                  f"a shell pattern, say so with --extra-glob, which expands it; "
                  f"if it is a directory of inputs, name the directory (a "
                  f"directory is hashed by its contents).",
                  file=sys.stderr)

    # …and the louder version of the same trap, for a pattern that WAS expanded
    # and came back empty. A missing path might be a typo; an empty set is a
    # subject that has gone, and it is the case that matters, because the whole
    # reason a caller reached for a pattern instead of a list is that the set
    # changes shape as files are added and removed. Naming the count it found
    # is what makes "the set is gone" readable as such rather than as a cache
    # that has quietly stopped covering its subject.
    for pat in empty_globs:
        print(f"[checked_run] {args.name}: --extra-glob {pat!r} matched NO "
              f"files, so this test's key is now blind to a set that has just "
              f"changed shape (or to a pattern that does not spell what it was "
              f"meant to). The other --extra-glob patterns still apply, and the "
              f"run continues: a broken key is worth saying out loud, not worth "
              f"turning into a failure nobody can act on.",
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
