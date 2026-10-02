# PERF: a per-character `str` scan peaked at 247 MB over a 60 MB ceiling

## Status (2026-10-02 — CLOSED, and the 60 MB ceiling was RIGHT)

This doc asked which of two things was the defect: the scan allocating per
character, or the ceiling being wrong. **It was the implementation, the ceiling
was correct, and the ceiling was left where it was** — which is the outcome the
doc's own reasoning pointed at ("nobody has said which of the two is the
defect") and the one `bugs/PERF_char_scan_leak_residual_21_bytes_per_char.md`
then settled.

`test_gimple_runner.py::gimple_char_scan_allocates_nothing_per_character`
measured **246.7 MB** against its own **60 MB** ceiling. It now measures
**1.6 MB**, so the row passes with a 37x margin rather than being re-baselined.
The fix and the measurement behind it are in
`bugs/PERF_char_scan_leak_residual_21_bytes_per_char.md`, whose Status section
is the whole story: one `malloc(2)` per character, from a string subscript
spelled `mojo_cstr_slice(s, i, i + 1)` because gimple refuses a `char`-typed
argument, now reached through a new `mojo_char_at(char *, int64_t)` that answers
from the same shared immortal character table `c == "x"` in the same loop body
already used.

The two candidate explanations this doc separated were the right two, and the
measurement that separated them is the one the other doc ran: the allocation
COUNT was ~4.8 million, one per character, so the row's NAME was accurate and
the fix belonged in the char-append path. Not raising the ceiling is the
outcome the doc's second bullet asked for explicitly — "the right action is to
lower the ceiling to the measured steady state WITH the measurement recorded in
this file" applies to a ceiling that is too HIGH, and this one was too low.

`gimple_char_concat_never_frees_shared_character`, the neighbouring case that
peaks at 52-28 MB and passes, is the invariant the fix had to preserve (a
shared character string is never freed) and it still passes.

## What it does

`test_gimple_runner.py::gimple_char_scan_allocates_nothing_per_character`
asserts the printed value `4800000` (which it gets) and a peak RSS at or below
**60 MB**. Measured peak: **246.7 MB**. The neighbouring case
`gimple_char_concat_never_frees_shared_character` peaks at 52.2 MB and passes.

So the row is a *performance budget*, not a correctness one, and it is over by
4x.

## Why it was filed and not fixed

Two reasons, and the first is the reason it belongs in `bugs/` at all:

1. `CLAUDE.md` makes "over 4 GB is a debt" a project-wide standard
   (`bugs/PERF_memory_over_4gb_is_a_bug.md`). 247 MB is far under that, so
   nothing in the repo's stated policy says this number is wrong — the number
   that is wrong is the 60 MB ceiling, which was set when the scan allocated
   nothing. The row is asserting a budget that the implementation stopped
   meeting, and nobody had said which of the two is the defect.
2. The honest answer is not knowable from a 4x-over number. The two candidates
   are (a) the scan now allocates per character, in which case the row's NAME
   is right and the implementation regressed; and (b) the scan's steady-state
   peak is dominated by something else entirely (a per-iteration buffer, a
   retained slice, the string arena) and the per-character part is still zero.
   Those need different fixes and opposite justifications for lowering the
   ceiling, and picking one by reading the code is how a budget row becomes
   either useless or rubber-stamped.

Candidate (b) is now excluded by measurement as well as by argument: the
allocation count was one per character, so the per-character part was the whole
of it and the peak has no other component left to find.

## What was run

```
python3 test_gimple_runner.py
```

(the peak is measured and reported by the suite's own harness, which is why
the figure appears in the failure line rather than needing a separate
`/usr/bin/time -l` run).

## The two measurements the next step asked for

1. **The ALLOCATION COUNT, not the peak.** "Allocates nothing per character" is
   a claim about the count, and it is directly testable. It was: one
   `malloc(2)` per character, 16.06 B/char against 16.1 B for a bare `malloc(2)`
   on the same machine, flat across a 4x range of loop counts. So the row's name
   was accurate and the fix was in the char-append path — which is where it went.
2. **Whether the memory was HELD rather than churned.** It was churned, and the
   slope settles it on its own: fragmentation and retention both give a slope
   that flattens or falls, and this one is flat to three significant figures with
   a ~0 intercept. A retained `MojoList` per iteration would have shown up as a
   floor; there is no floor.

So the doc should end with a number a reader can check — 1.6 MB against a 60 MB
ceiling, on the row that reads 246.7 MB today — which is the only part of it
that was missing.

`gimple_kinds_survive_a_sibling_list_being_freed` was the THIRD failure in the
same run and was a real SIGSEGV, not a budget; it is fixed, in
`bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md`. It is
recorded here only so the "261 passed / 3 failed" figure in this file is not
mistaken for a census of what is still broken. (That figure is itself history:
the current run is 294 passed / 10 failed, and nine of those ten are
pre-existing on `bc17a62b` — see the other doc's verification section.)