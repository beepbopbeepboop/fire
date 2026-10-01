# PERF: the tokenizer-scan leak is 15x smaller, not zero — 21 bytes per character remain

**Found 2026-10-01 while merging `worktree-agent-a4427eb542b05159d` (the leak
hunt) into a tree that already had eight other branches.** That branch's
`bugs/PERF_selfhost_memory_leak_hunt.md` records item 1 as

> FIXED (256 shared immortal strings; display freed after `in`). Test:
> `gimple_char_scan_allocates_nothing_per_character

and its test's own comment says "allocates nothing per character". On the
merged tree it is **not** zero, and the residual is linear in the character
count, so the test's 60 MB tripwire is red at 246.7 MB.

## What I ran and what I saw

`test_gimple_runner.py`'s own case, and the same program at two loop sizes so
the SLOPE is the measurement rather than one point on it (the method
`test_gimple_bounded_memory`'s docstring gives, and `doc/MEMORY.html` §8's
reason one size proves nothing):

    probe = subprocess.run([exe], env={..., 'MallocScribble': '1'})
    peak  = resource.getrusage(RUSAGE_CHILDREN).ru_maxrss

| tree | `range(50000)` | `range(200000)` | per iteration | per character |
|---|---|---|---|---|
| **pre-leakhunt** (13 leakhunt files reverted to their pre-merge content) | 1 128 628 224 | 4 512 661 504 | ~22.5 KB | ~310 B |
| **merged** (what this branch landed) | 78 790 656 | 310 034 432 | ~1.5 KB | ~21 B |

Both slopes are linear and neither is flat. So the merge is a real ~15x
improvement on the same construct, and the branch's "allocates nothing" claim
does not hold on a tree with other branches merged into it. The pre-leakhunt
row is the control that says the residual is not something this merge
introduced: the same shape leaks 15x more there.

`python3 test_gimple_runner.py` reports
`Results: 237 passed, 1 failed` with exactly this failure:

    FAIL  gimple_char_scan_allocates_nothing_per_character: stdout
    '4800000\n' (want '4800000\n'), peak RSS 246.7 MB (limit 60)

Note the **stdout is exactly right**. The program computes CPython's answer;
only the tripwire is red. Nothing else in the suite sees it, which is why the
case exists.

## What is already in place, so the next step does not re-derive it

Both halves of the branch's fix are present and verified in the generated C,
not just in the source:

* `runtime/fire_runtime.c`'s `mojo_char_to_str` returns a `static char
  tbl[256][2]` — one immortal string per byte value, no allocation.
* `_lower_in_impl_values` emits `mojo_list_free (_t7);` after the membership
  test for a `TupleExpr` right-hand side, and `_free_fresh_container` for a
  list/set/dict display. Confirmed by compiling the case and reading the C.

So the ~21 B/char is something ELSE in the same loop. The candidates, in the
order I would check them:

1. `var c = s[i]` — a `String` subscript. If it boxes a one-character string
   per index, that is one allocation per character and nothing frees it. The
   generated C for the case is the place to read: `c` is a `char *` temp
   assigned from the subscript, and there is no matching free.
2. `c == "x"` and `c in (...)` both go through `mojo_char_to_str`, which is
   allocation-free, so they are not it — but the `elif c in (')', ']', '}')`
   arm allocates its OWN tuple display, so there are two displays per
   character on the `elif` path and the free must be on both paths.
3. `mojo_list_free` may release the block to the allocator without shrinking
   the process's high-water mark, in which case the slope is fragmentation
   rather than a leak — which `doc/MEMORY.html` §8's two-size method is
   designed to distinguish: run it at 20000 and 200000 and compare the SLOPE.
   A slope of ~0 with a high floor is fragmentation, and the honest fix is a
   different tripwire shape (a floor, not a slope), stated as such.

Item 3 is cheap to settle and changes the answer, so it is first.

## Why the tripwire is not simply raised

The 60 MB limit is the branch's, and the case's purpose is to catch the leak
returning. Raising it to the measured 310 MB would convert a red test into a
green one that no longer distinguishes 21 B/char from 310 B/char — which is
the "silence an error" this repo's rules forbid, and the `memory` section of
CLAUDE.md's own reading: a ceiling that has to be raised after every merge is
a ceiling that measures the merges, not the program. The test is left red on
purpose, with this doc as the next step.

## Where

* the case: `test_gimple_runner.py`, `gimple_char_scan_allocates_nothing_per_character`
* the two halves that ARE fixed: `runtime/fire_runtime.c` `mojo_char_to_str`,
  `mojo/backend_gimple/emit_exprs.py` `_lower_in_impl_values`
* the method: `test_gimple_runner.py` `test_gimple_bounded_memory`'s docstring,
  `doc/MEMORY.html` §8