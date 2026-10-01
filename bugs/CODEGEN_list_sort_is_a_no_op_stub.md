# `list.sort()` is a no-op stub — the list is returned unsorted, exit 0

**State: OPEN.** Not fixed. Found 2026-09-29 while fixing the bytes
residue in `hard/CODEGEN_bytes_silent_wrong_values.md`; it is a LIST bug and
was deliberately left out of that work, which is what this doc is for.

## What I ran and what I saw

`.tmp/cases/sortbug.mojo` (the harness is gone; the program is three
lines), compiled through the gimple path with `gimple_codegen.compile_to_gimple`
+ `gcc -fgimple` against `runtime/fire_runtime.c`, and run under CPython for
the oracle:

    l = [3, 1, 2]
    l.sort()
    print(l)
    m = ['c', 'a', 'b']
    m.sort()
    print(m)
    n = [3, 1, 2]
    print(sorted(n))

| | CPython | compiled |
|---|---|---|
| `l.sort(); l` | `[1, 2, 3]` | `[3, 1, 2]` |
| `m.sort(); m` (strings) | `['a', 'b', 'c']` | `['c', 'a', 'b']` |
| `sorted(n)` (the FUNCTION) | `[1, 2, 3]` | `[1, 2, 3]` |

Both `list.sort()` lines are **silently wrong with exit 0** — the worst
shape, because the list is returned in its original order and nothing says
so. `sorted()` the function is correct, so the two spellings of the same
operation disagree, which is its own trap: `x = sorted(l)` works and
`l.sort(); x = l` does not.

## Mechanism

`runtime/fire_runtime.c`:

    void mojo_list_sort(MojoList *l) { (void)l; /* stub */ }

and `mojo/backend_gimple/emit_methods.py` emits a call to it directly:

    if method in ('sort', 'reverse', 'clear'):
        gen._emit(f"  mojo_list_{method} ({ov});")

Its siblings `reverse` and `clear` are real; `sort` is the only stub of the
three. The 2026-09-29 tuple work added the tuple-marker guard here (so
`(1,2).sort()` now refuses with CPython's `AttributeError` rather than
silently doing nothing) and recorded in the function's own comment that the
sorting itself is still missing — that comment is the honest state.

## Why it was not fixed there

The bytes work was a bytes change, and a real sort needs a decision this
runtime has not made: what comparator? A `MojoList` slot is a raw
`int64_t` holding either a number, a pointer (string) or a double's IEEE
bits, with no per-element tag, so `mojo_list_sort` cannot know which it is
looking at. The call site usually CAN (codegen tracks `_elem_types`), so the
shape that works is: pass the statically known element kind to a runtime
sorter the way `mojo_list_eq` and `mojo_list_count_{int,str,bytes}` now do.
That is the same convention three other fixes in the same file already
follow, so it is not a new design — but it is a change to the sort path, not
to the bytes path, and it was not in scope.

## Exact next step

1. Add `mojo_list_sort_int(l)` / `_str` / `_bytes`, mirroring
   `mojo_list_count_int`'s shape (one slot reader, one comparison).
2. Thread the element kind through from `gen._elem_of(ov)` at the
   `method in ('sort', 'reverse', 'clear')` site, as `_lower_bytes_method`
   and `_repr_value` already do.
3. **Decide the unknown-element fallback explicitly.** With no recorded
   element type, comparing raw slots orders strings by ADDRESS — a
   non-deterministic order that also breaks bootstrap byte-identity. That
   must be a refusal or a documented refusal-to-refuse, never a silent
   address sort. `mojo_list_sorted_str` already exists for the string case;
   `sorted()` on a list of strings is correct today, so do not regress it.
4. Differential test: every list of 0/1/2/3 elements over a small alphabet,
   ints and strings, against CPython — the same shape as the
   `mojo_is_kind` verification recorded in the bytes doc (4192 pairs, 0
   diffs).

Not filed elsewhere: `bugs/` had nothing on this, and
`bugs/hard/README.md` does not list it. `list.sort` is not a "hard" bug in
the README's sense (a silent miscompile, yes, but a small and local one),
so `bugs/` is the right home.

## Suite-bucket note (integrator's call, not mine)

While verifying the bytes work I also ran `test_gimple_async_runner.py`: it
is **2 passed, 36 failed**, and the failures are pre-existing — the same
count at `HEAD` with my work stashed, so not a regression from this branch.
`tools/suite.py` records it as `gimple-async-runner` with
`expect='36 failing: the gimple async runner, an area with no gate coverage
until now'` and an EMPTY bucket list (`[]`), so it is deliberately not run
by `make check` or `make gate`.

Flagged rather than registered, per the assignment: registering it is the
integrator's decision. Note the marker is a blanket "36 failing" rather
than a per-case reason, and the dominant failure text is uniform
("expected a non-empty generated .cpp — this source doesn't actually
contain a Step-B-supported async function"), which reads more like a
harness/expectation mismatch than 36 independent defects. Whatever the
resolution, it should not be resolved by relaxing the assertion.
