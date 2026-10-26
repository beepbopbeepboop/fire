# `formal-runtime-link` is RED on master: FORMAL.md §6 phase 2's `word-shaped` row says 272, `runtime_abi()` says 273

**Area:** `FORMAL.md` §6 phase 2 (line ~527) and
`test_formal_runtime_link.py::test_both_architectures_agree`. **Status: OPEN,
measured 2026-10-13 during an unrelated formal task.** The fix is already
authored on `work/formal315-docs` (commit `9eaab4ce`, "FORMAL.md: the phase-2
surface is 273/217/177, and the doc-truth pin reads §6"); it is filed here only
because that branch is unmerged and the red is live on `master`.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py
...
FAIL  arm64: 273 word-shaped entry points in `runtime_abi()`, FORMAL.md §6 phase 2 publishes 272
FAIL  arm64: 217 word-shaped entry points exported, FORMAL.md §6 phase 2 publishes 216
FAIL  arm64: 177 reachable with no heap handle, FORMAL.md §6 phase 2 publishes 176
(and the same three for x86_64)
183 passed, 6 failed, 189 checks
```

Six checks, three per architecture, and they are NOT this task's doing: the
only files this branch changes are `build_stdlib_dylib.py` (the workdir leak),
its runtime-link test row, the proof census baseline and `tools/suite.py`.

## Why

`38d19a52` added `mojo_str_register` to `runtime/fire_runtime.h` without moving
the ladder. `791ca1d5` (the `--fix` census run) rewrote the **§2.2** census table
to **273** (`272 -> 273 word-shaped`) but **§6 phase 2** — a different table in
the same file — is left at `272 | 216 | 176`, and that is the table
`test_formal_runtime_link.py` reads (`_published_phase2_surface`).
`runtime_abi()` now holds 273 word-shaped entry points on both backends, so the
document is one row stale and the job is red.

## The exact next step

`9eaab4ce` on `work/formal315-docs` is the fix: update §6 to `273 / 217 / 177`
and make the doc-truth pin read §6. Land (or re-author) it, then `git rm` this
doc. `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_runtime_link.py` should be 189/189.

## Reproducing

```console
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py
# 183 passed, 6 failed, 189 checks
```
