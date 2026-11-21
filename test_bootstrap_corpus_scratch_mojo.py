#!/usr/bin/env python3
"""Pin the c0182fd365 gate red: a scratch probe must not be a bootstrap job.

`tools/suite.py::tracked_mojo_files()` feeds every TRACKED top-level `*.mojo`
to the three `bootstrap-stage*-dumps` fan-outs, so "is this file a gate job?"
is exactly "is it tracked source?". That is the right rule (it replaced a glob
that raced `test_ab_native.py`'s transients), but it means a scratch file that
`git add -A` sweeps in stops being scratch and starts being a gate job.

`tmphemc8yln.mojo` was that file: a six-line `fcntl` probe committed by
3d32c0e66 (a formal-branch commit that ran `git add -A`), which then failed
`bootstrap-stage2-dumps:tmphemc8yln.mojo` at c0182fd365. There was no compiler
defect to find -- the item existed only because the probe was tracked. The fix
removes the probe and ignores the shape (`/tmp*.mojo`) so the next `git add -A`
cannot recreate it.

Two assertions, and each one is false on the pre-fix tree:

  1. the probe is not tracked, and therefore not a bootstrap item. Before the
     fix `git ls-files` names it and `tracked_mojo_files()` returns it.
  2. a `mkstemp`-shaped `.mojo` at the repo root is gitignored (that is what
     makes `git add -A` skip the next one). Before the fix `.gitignore` has no
     `/tmp*.mojo` rule and `git check-ignore` exits 1.

The third assertion is the guard on the guard: the ignore must stay
root-anchored, or a real fixture added under `mojo/` would be silently
excluded from every `git add`. It passes before the fix, which is the point --
it fails if someone "strengthens" the rule with an unanchored `tmp*.mojo`.

Run: python3 test_bootstrap_corpus_scratch_mojo.py     (0.0 s, no build)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import suite                                                      # noqa: E402

# The probe 3d32c0e66 swept in, relative to the repo root.
PROBE = 'tmphemc8yln.mojo'
# `tempfile.mkstemp(prefix=..., suffix='.mojo')` in its default shape: "tmp"
# plus eight random characters. Not created anywhere -- `git check-ignore`
# answers from the ignore rules, and creating it at the root is the very
# accident this file is about.
SCRATCH_SHAPE = 'tmpzzzz1234.mojo'


def git(*args):
    return subprocess.run(['git', '-C', HERE, *args],
                          capture_output=True, text=True)


def test_the_probe_is_not_a_bootstrap_item():
    tracked = git('ls-files', '--error-unmatch', '--', PROBE)
    assert tracked.returncode != 0, (
        f'{PROBE} is TRACKED again (git ls-files: '
        f'{tracked.stdout.strip()!r}). Every tracked top-level .mojo is a '
        f'bootstrap-stage*-dumps item, so a scratch probe becomes a gate job '
        f'that can only fail or silently widen the corpus.')

    # The item list is the registry's own, not a re-derivation: if the runner
    # ever stops using tracked_mojo_files() this assertion is what notices.
    assert len(suite.MOJO_FILES) > 20, (
        f'only {len(suite.MOJO_FILES)} bootstrap .mojo items; the corpus is '
        f'empty, so "the probe is not an item" would be true for the wrong '
        f'reason')
    assert PROBE not in suite.tracked_mojo_files(), (
        f'{PROBE} is a bootstrap fan-out item')
    assert PROBE not in suite.MOJO_FILES, (
        f'the live BOOTSTRAP_INPUTS list still carries {PROBE}')


def test_a_tempfile_shaped_root_mojo_is_gitignored():
    scratch = git('check-ignore', '-q', '--', SCRATCH_SHAPE)
    assert scratch.returncode == 0, (
        f'a mkstemp-shaped .mojo at the repo root ({SCRATCH_SHAPE}) is not '
        f'gitignored, so the next `git add -A` turns another scratch probe '
        f'into a bootstrap job: .gitignore has no `/tmp*.mojo` rule')

    # Root-anchored: the same name under mojo/ must stay addable, or a real
    # fixture there is silently dropped from every `git add`.
    nested = git('check-ignore', '-q', '--', 'mojo/' + SCRATCH_SHAPE)
    assert nested.returncode != 0, (
        f'the scratch ignore rule is not root-anchored: it also covers '
        f'mojo/{SCRATCH_SHAPE}, so a fixture in that directory would be '
        f'silently ignored by every `git add`')


def main():
    test_the_probe_is_not_a_bootstrap_item()
    test_a_tempfile_shaped_root_mojo_is_gitignored()
    print('bootstrap corpus scratch probe: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
