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

The real fix was never the sweep's, and it has landed: `fire.py`'s
`build_executable` wrote every one of its intermediates — `.ci`, `.o`,
`_runtime.o`, `_gen.cpp`, `_gen.o` — into the process's CWD, and only
`test_module_cache.py` and `jit/arm64.py` passed `work_dir`; `fire.py`'s own
`build` command did not. They now go in a private scratch DIRECTORY derived
from `output` (falling back to the input file's own directory), created
uniquely per build so two same-basename builds cannot collide even inside one
directory, and removed on every return path — which also removed the collision
hazard, not just the litter. Pinned by `test_selfhost.py`'s
`build_scratch_is_private_and_removed`.

What landed here is the cheap half: `*_gen.cpp` is in `.gitignore`, beside the
`*.ci` and `*.o` entries that already covered the other three intermediates,
so this file can no longer be the one that turns a build into a commit. Two
such files had already been committed — `update_file_gen.cpp` and
`generate_sre_constants_gen.cpp`, both by `e98ea1f8` — and both are removed.

Keep `cwd=HERE` in `py314_harness._build_uncached`. It used to be the only
thing standing between the sweep and a dirtied repository root, and the advice
here was to drop it; that advice is now wrong twice over. The intermediates
follow `-o out_path`, which is a `tempfile.mkstemp` path, so they are created
and removed under TMPDIR whatever the CWD is. And `cwd=HERE` is what lets
`fire.py build` resolve the compiler's own relative imports, so dropping it
would trade a stray `.cpp` for a build that cannot find `gimple_codegen`.

## How to confirm the fix

    $ python3 tools/suite.py formal-imports   # or any build, from the repo root
    $ git status --short --untracked-files=all | grep -c '\.cpp$'   # 0

and, for the sweep itself, `python3 test_py314_full.py --root <tree>` leaving
`git status --short` empty at the end.