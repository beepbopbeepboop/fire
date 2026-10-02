# PERF: a per-character `str` scan allocates 4.8 MB and peaks at 247 MB, over a 60 MB ceiling

Found 2026-10-30 while running `test_gimple_runner.py` (the `gimplerunner` row
of the `check` bucket) for unrelated work. Red on this tree, and red before
that work: A/B-verified by reverting the whole change under test and
re-running the file — 261 passed / 3 failed with and without, identical peak
figure (246.7 MB) both ways, so it is not a measurement of anything that
changed here.

## Status: OPEN, pre-existing, and the shape of the ceiling is the interesting part.**

## What it does

`test_gimple_runner.py::gimple_char_scan_allocates_nothing_per_character`
asserts the printed value `4800000` (which it gets) and a peak RSS at or below
**60 MB**. Measured peak: **246.7 MB**. The neighbouring case
`gimple_char_concat_never_frees_shared_character` peaks at 52.2 MB and passes.

So the row is a *performance budget*, not a correctness one, and it is over by
4x.

## Why it is filed and not fixed

Two reasons, and the first is the reason it belongs in `bugs/` at all:

1. `CLAUDE.md` makes "over 4 GB is a debt" a project-wide standard
   (`bugs/PERF_memory_over_4gb_is_a_bug.md`). 247 MB is far under that, so
   nothing in the repo's stated policy says this number is wrong — the number
   that is wrong is the 60 MB ceiling, which was set when the scan allocated
   nothing. The row is asserting a budget that the implementation stopped
   meeting, and nobody has said which of the two is the defect.
2. The honest answer is not knowable from a 4x-over number. The two candidates
   are (a) the scan now allocates per character, in which case the row's NAME
   is right and the implementation regressed; and (b) the scan's steady-state
   peak is dominated by something else entirely (a per-iteration buffer, a
   retained slice, the string arena) and the per-character part is still zero.
   Those need different fixes and opposite justifications for lowering the
   ceiling, and picking one by reading the code is how a budget row becomes
   either useless or rubber-stamped.

## What was run

```
python3 test_gimple_runner.py
```

(the peak is measured and reported by the suite's own harness, which is why
the figure appears in the failure line rather than needing a separate
`/usr/bin/time -l` run).

## Next step

One measurement separates the two candidates, and it is cheap:

1. Run the fixture under `/usr/bin/time -l` (or `leaks`/`heapshot` on the
   built binary) and look at the ALLOCATION COUNT, not the peak. "Allocates
   nothing per character" is a claim about the count, and it is directly
   testable: 4 800 000 characters with one malloc each is 4.8 million calls,
   which `DTrace`'s `malloc_count` or a `malloc` interposer answers in one
   run. If the count is ~4.8 million, the row's name is accurate and the fix
   is in the char-append path (`mojo_str_cat` / `mojo_char_to_str`).
2. If the count is small and the peak is still 247 MB, the memory is held, not
   churned: look for a retained `MojoList`/buffer per iteration, which points
   at the same closure the neighbouring "never frees shared character" case
   already covers — and in that case the right action is to lower the ceiling
   to the measured steady state WITH the measurement recorded in this file,
   because a ceiling nobody re-derives is the thing that rots.

Either way the doc should end with a number a reader can check, which is the
only part of it that is missing now.

`gimple_kinds_survive_a_sibling_list_being_freed` was the THIRD failure in the
same run and was a real SIGSEGV, not a budget; it is fixed, in
`bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md`. It is
recorded here only so the "261 passed / 3 failed" figure in this file is not
mistaken for a census of what is still broken.