# `test_py314_full.py` still leaves a generated `.cpp` at the repo root: `--out` moved the REPORTS, not the build's output

## Status

OPEN — found 2026-10-03 while merging `work/merge-bugs3-r4` into master and
running the narrow tests for everything the merge touched. Not fixed here: it
is a question about where `fire.py build` puts its own generated output, which
is the compiler's behaviour and not this sweep's, and the sweep is a Tier-3
investigation tool that no gate runs.

`bugs/UNTESTED.md` §4.1's Status has been corrected in the same commit: it
claimed §4.1 "is fixed" and quoted the `.cpp` as part of what is fixed. The
first half of that is true and measured below; the second half is not.

## What was run

    $ cd <worktree> && python3 test_py314_full.py       # default --root

Left behind, untracked, at the repository root:

    grammar_snippet_gen.cpp      9419 bytes

The run was killed at a 50-minute cap. Nothing else was written into the
tracked tree — `git status --short` was empty apart from that one file — which
is the half of §4.1 that the `--out` change really did fix, and it is worth
saying so plainly rather than leaving the whole item marked open.

## What was expected

§4.1's own measurement lists two artefacts of a 300-second run: 25 new
`bugs/<CATEGORY>_<path>.md` files and a `grammar_snippet_gen.cpp` at the repo
root. The fix moved the reports to `--out` and did not mention the second one,
so reading the Status as written says both are gone. One is.

## Why it still happens

The sweep is not what writes it. `test_py314_full.py` contains the string
`grammar_snippet_gen` exactly once, in its own docstring:

    $ grep -n grammar_snippet_gen test_py314_full.py
    23:  `grammar_snippet_gen.cpp` at the repo root, and the failure mode is not who ran

So the file comes out of a `fire.py build` of one file in the scanned tree,
landing in the process's CWD — which for a sweep started at the repository root
is the repository root. `--out` relocates the sweep's own writes; nothing
relocates a build's generated C++.

The real fix is not the sweep's: `fire.py`'s `build_executable` writes every
intermediate into the process's CWD and only `test_module_cache.py` and
`jit/arm64.py` pass `work_dir` — `fire.py`'s own `build` command does not. That
is filed, with the collision hazard it creates, as
`bugs/CODEGEN_fire_py_writes_build_intermediates_into_the_cwd.md`, and it is a
compiled-path change, so it owes a full `make gate`.

What landed here is the cheap half: `*_gen.cpp` is in `.gitignore`, beside the
`*.ci` and `*.o` entries that already covered the other three intermediates,
so this file can no longer be the one that turns a build into a commit. Two
such files had already been committed — `update_file_gen.cpp` and
`generate_sre_constants_gen.cpp`, both by `e98ea1f8` — and both are removed.

Dropping `cwd=HERE` in `py314_harness._build_uncached` is still worth doing on
its own: it is one keyword and it makes the harness leave nothing behind. But
do not record §4.1 as closed on the strength of it.

## How to confirm the fix

    $ python3 tools/suite.py formal-imports   # or any build, from the repo root
    $ git status --short --untracked-files=all | grep -c '\.cpp$'   # 0

and, for the sweep itself, `python3 test_py314_full.py --root <tree>` leaving
`git status --short` empty at the end.