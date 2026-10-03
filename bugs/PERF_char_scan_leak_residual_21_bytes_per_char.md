# PERF: the tokenizer-scan leak is down to ONE unfreed `malloc(2)` per character, and it is `s[i]`

**Status: the question is settled; the bug is not fixed.** Measured 2026-10-01
on this tree, and the answer is one named line rather than three candidates.
The tripwire in `test_gimple_runner.py` stays red on purpose — see the last
section for why raising it is worse than the leak.

## What the previous version of this doc left open, and what it was

It left three candidates, in the order it wanted them checked:

1. `var c = s[i]` — a String subscript that boxes a one-character string per
   index, one allocation per character, nothing frees it.
2. the `elif c in (...)` arm allocating its own tuple display, with the free
   on only one of the two paths.
3. the residual being *fragmentation* rather than a leak — which the two-size
   method was designed to distinguish, and which would have changed the answer.

**Candidate 1 is it, and 2 and 3 are both refuted.** The slope is one
`malloc(2)` per character and nothing else; 16.06 bytes per character measured
against 16.1 bytes for a bare `malloc(2)` on this machine, which is the
entire residual to within measurement noise.

## The measurement: a slope, and how big

The program is `test_gimple_runner.py`'s own case, with the loop count as a
parameter (`tools/mem_slope.py`'s own method, four sizes rather than two
because one slope is a line through two points by construction):

| `range(N)` | peak RSS | slope from the previous row |
|---|---|---|
| 25 000 | 32.2 MB | |
| 50 000 | 62.9 MB | 1285.2 B / iteration |
| 100 000 | 124.1 MB | 1285.2 B / iteration |
| 200 000 | 246.7 MB | 1285.0 B / iteration |

Flat to three significant figures across a 4x range. **A leak, not
fragmentation** (candidate 3): fragmentation gives a *falling* slope, because a
freed block is reused by the next identical allocation, so a program's growth
per iteration decreases as its steady state is reached. This one does not
move, and the intercept is ~0 — there is no floor here at all, which is why the
honest fix is a different tripwire shape rather than a floor.

`line` is 80 characters (`"(x[x{}x]) " * 8`), so

    1285.0 B / iteration  ÷  80 characters  =  16.06 B per character

and the reference measurement for the allocator itself, on this machine:

| program | 500k calls | 1M | 2M | slope |
|---|---|---|---|---|
| `malloc(2)` in a loop, never freed | 9.1 MB | 16.8 MB | 32.1 MB | **16.1 B / malloc** |
| `mojo_cstr_slice(s, i, i+1)` in a loop, never freed | 9.2 MB | 16.8 MB | 32.2 MB | **16.1 B / call** |

16.06 against 16.1: the residual is one one-character `malloc` per character,
and there is no room in the difference for a second allocation per character.

**Candidate 2 is refuted by construction.** A second program identical except
that the two `c in (...)` arms are deleted — same subscript, same
`c == "x"`, no tuple displays — measures 1285.0 B/iteration, the same slope to
four figures. The displays are freed on both paths
(`mojo_list_free (_t7)` and `mojo_list_free (_t15)` in the generated C) and
cost nothing that accumulates.

## Where it is, exactly

The generated C for the loop body, from
`python3 -c "from gimple_codegen import compile_to_gimple; ..."` on the probe:

    bb_4:
      _t3 = (int64_t) i;
      _t4 = _mojo_at_char (s, _t3);              /* static char * _mojo_at_char(char *p, int64_t n) { return p + n; } */
      _t5 = _t3 + 1LL;
      _t6 = mojo_cstr_slice (s, _t3, _t5);      /* ← malloc(2), never freed */
      c = _t6;
      _t7 = _slit_10000; _t8 = c; _t9 = _t7;
      _t10 = mojo_cstr_cmp (_t8, _t9);
      _t11 = _t10 == 0;

One allocation, at `_t6`, and no `mojo_free`/`mojo_list_free` of `c` anywhere
in the function. `mojo_cstr_slice` is a `malloc(n + 1)` + `memcpy` +
NUL-terminate (`runtime/fire_runtime.c:1901`), so a one-character subscript is
a two-byte `malloc` per index. `_mojo_at_char` is `p + n` and allocates
nothing; `_t4` is in fact dead in this shape.

The emitter is `mojo/backend_gimple/emit_calls.py` — two sites, one for a
string boxed as `int64_t` (`emit_calls.py:6892`) and one for a plain `char *`
(`emit_calls.py:7090`), and both spell the one-character subscript as

    mojo_cstr_slice (ptr, idx64, idx64 + 1LL)

The comment above the first one already says the right thing about the
*value* — "`s[i]` on a str is a 1-char STRING, not a character code … the
canonical use is `rest[0]` comparing against a quote literal" — and cites
`mojo_char_to_str` as "the existing helper". The value is right; the
**representation** is the leak.

## The fix, and the one thing to be careful about

Lower the one-character subscript to the helper that already exists and
already allocates nothing:

    runtime/fire_runtime.c: mojo_char_to_str(char) returns
        `static char tbl[256][2]` — one immortal string per byte value.

`c == "x"` in the very same loop body is *already* lowered through it, and
`test_gimple_runner.py`'s `gimple_char_concat_never_frees_shared_character`
already pins the invariant that made that safe: **a shared character string is
never freed.** That is the whole risk, and it has to be checked rather than
assumed — `mojo_list_free_owned_strs` (`runtime/fire_runtime.c:1386`) frees
every element of a list the codegen matched to an owning function, and a
`[s[0], s[1]]` that reached one of those would then be freeing a static.

So the fix is two lines of emitter **plus** a look at whether any
owning-container path can receive a `s[i]`. That is a real review of
`emit_infra.py`'s `_OWNS_STR_ELEMS` set against the subscript lowering, and it
is why this is written down as a next step rather than landed: it changes
`mojo/backend_gimple/emit_calls.py`, which is another claim's write set, and it
owes the full `make gate` (a `char *` representation change is invisible to
every interpreter-side suite).

Two cheaper shapes, for the record, and why neither is the one to take:

* **free the slice** after the last use of `c`. That is what
  `_lower_in_impl_values` does for a tuple display, and it works — but it puts
  a `mojo_free` on the value's last use, which is a dataflow question the
  emitter currently does not answer for a local that may be read again. Wrong
  in that direction is a use-after-free, and `MallocScribble` in the runner
  turns it into a wrong answer rather than a crash.
* **lower `s[i]` to a `char` and widen at the use.** Rejected in the tree
  already, for a stated reason: "`s[i]` on a str is a 1-char STRING, not a
  character code … returning a bare `char` broke" things, and `gimple`
  rejects a `char` argument outright ("invalid argument to gimple call").

## Verification, and what it costs

`python3 test_gimple_runner.py` is the one file that covers this: it holds both
the tripwire (`gimple_char_scan_allocates_nothing_per_character`, 60 MB) and
the shared-character invariant (`gimple_char_concat_never_frees_shared_character`).
Both must stay green. It is a compiled-path change, so it owes `make gate` too,
which is the integrator's and not a worker's.

## Why the tripwire is not simply raised

The 60 MB limit is the leakhunt branch's, and the case's purpose is to catch
the leak returning. Raising it to the measured 247 MB would convert a red test
into a green one that no longer distinguishes 16 B/char from 150 B/char — which
is the "silence an error" this repo's rules forbid, and it is why
`bugs/PERF_memory_over_4gb_is_a_bug.md`'s own reading applies to a test
tripwire as much as to a class: a ceiling that has to be raised after every
merge is a ceiling that measures the merges, not the program.

The tripwire's own number is also *correct* for the workload it guards. The
docstring says the loop is sized so "the leak, if back, is gigabytes"; the
residual that is there now is 16 B per character, and 16 B/char is
indistinguishable from zero at a size that would catch 150 B/char. Once the
subscript stops allocating, the case passes at 60 MB with room to spare, and
that is the moment the number is revisited.
