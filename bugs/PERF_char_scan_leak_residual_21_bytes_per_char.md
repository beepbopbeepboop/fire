# PERF: the per-character `str` scan allocated one `malloc(2)` per character

## Status (2026-10-02 — FIXED, by the change this section describes)

The question this doc spent its length settling ("which of the three candidates
is the residual?") was answered correctly and the answer was acted on: candidate
1, `s[i]`. `test_gimple_runner.py`'s
`gimple_char_scan_allocates_nothing_per_character` measured a **246.7 MB** peak
against its own **60 MB** ceiling and now measures **1.6 MB**, and the
neighbouring `gimple_char_concat_never_frees_shared_character` — the invariant
that made this fix safe to make — still passes at 27.6 MB.

The mechanism, in one line: gimple refuses a `char`-typed argument, so
`mojo_char_to_str(char)` was not callable from generated code and the codegen
spelled a string subscript as `mojo_cstr_slice(s, i, i + 1)` instead — a
`malloc(2)` + `memcpy` per character that nothing owns. One new runtime entry
point removes the need for the slice:

```c
char *mojo_char_at(char *s, int64_t i);
```

It takes an int64_t INDEX (which gimple is happy with), applies exactly
`mojo_cstr_slice`'s bounds — a negative index resolves against the real length,
an index at or past the end is `""` — and returns `mojo_char_to_str(s[i])`, i.e.
one of the 256 shared immortal strings that `c == "x"` in the very same loop
body already used. `memchr`, not `strlen`, for the non-negative case, for the
reason `mojo_cstr_slice` uses it: a scan over a long string must not re-scan the
whole thing once per character.

Five call sites, all of which were the same one-character subscript under a
different spelling:

| site | shape |
|---|---|
| `mojo/backend_gimple/emit_calls.py` (boxed-string arm) | `s[i]` where `s` is a str boxed as `int64_t` |
| `mojo/backend_gimple/emit_calls.py` (plain `char *` arm) | `s[i]` |
| `mojo/backend_gimple/emit_loops.py` `_gen_for_cstr` | `for c in s` |
| `mojo/backend_gimple/emit_loops.py` (`_compr_cstr_loop`'s twin) | the character comprehension's index loop |
| `mojo/backend_gimple/emit_resolve.py` | the `sorted(set(s))` character comprehension |
| `mojo/backend_gimple/cpp_core.py` | the C++ backend's `s[i]` inside a generator body |

### The one risk the doc flagged, checked rather than assumed

The doc's concern was `mojo_list_free_owned_strs` freeing a shared static. It
cannot, and the reason is structural rather than lucky: a value is only ever
freed through `owned_free_fn_for`, which reaches `free` for a `char *` only when
the value is in `gen._fresh_vals`, and `_emit` puts a value there only when the
emitted line assigns from a function in `_FRESH_STRING_RETURNS`.
`mojo_char_at` is deliberately **absent** from that set — beside
`mojo_char_to_str`, with the reason written down — so no generated path can emit
a `free()` of this value. `_OWNS_STR_ELEMS` is likewise unaffected: it names
`mojo_str_split`/`mojo_str_splitlines`, and a list built by either gets its
elements from those functions, never from a subscript. And the free direction
that would matter runs the other way: a subscript temp that used to be marked
fresh (and so could be freed) simply is not marked any more, which leaks
nothing because there is nothing to free.

### Verification

* `python3 test_gimple_runner.py` — 294 passed, 10 failed. Nine of those ten
  fail identically on a pristine `git archive bc17a62b` extraction
  (`gimple_bool_annotated_struct_field` x2, `gimple_bytes_*` x4,
  `gimple_dict_of_bool_values`, `gimple_sorted_string_key_runtime_built`,
  `gimple_tuple_dict_key_is_content_keyed`); the tenth was this file's own new
  case, since fixed. The pre tree's tenth is this file's
  `gimple_char_scan_allocates_nothing_per_character`, which this change turns
  green. **This is a `char *` representation change, so it owes the full
  `make gate` — `test_gimple_runner.py` alone is not sufficient evidence** and
  the integrator should run it.
* Behaviour spot-checked against CPython for `s[0]`, `s[-1]`, `s[-5]`, a
  past-the-end index, `[c for c in s]`, `sorted(set(s))`, `list(s)`,
  `"".join`, `s[a:b]`, `s[::2]`, building a dict from a scan, and
  `s.find/.upper/.lower/.split`: all identical. The one difference is unchanged
  and pre-existing — a past-the-end index returns `""` here where CPython raises
  `IndexError`; `mojo_cstr_slice` did exactly the same.

---

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
move, and the intercept is ~0 — there is no floor here at all, which is why
the honest fix is a different tripwire shape rather than a floor.

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

## Where it was, exactly

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
NUL-terminate (`runtime/fire_runtime.c:2036`), so a one-character subscript is
a two-byte `malloc` per index. `_mojo_at_char` is `p + n` and allocates
nothing; `_t4` is in fact dead in this shape.

## Two shapes the doc rejected, and why the answer was neither

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

  **This is the constraint the fix had to design around**, and it is worth
  restating because it is the whole reason the leak existed: the rejection is
  not about *returning* a char, it is about *passing* one. `mojo_char_at` takes
  an int64_t index and returns a `char *`, so nothing ever passes a char.

## Why the tripwire was not simply raised

The 60 MB limit was the leakhunt branch's, and the case's purpose is to catch
the leak returning. Raising it to the measured 247 MB would have converted a
red test into a green one that no longer distinguishes 16 B/char from
150 B/char — which is the "silence an error" this repo's rules forbid, and it
is why `bugs/PERF_memory_over_4gb_is_a_bug.md`'s own reading applies to a test
tripwire as much as to a class: a ceiling that has to be raised after every
merge is a ceiling that measures the merges, not the program.

The tripwire's own number was also *correct* for the workload it guards. The
docstring says the loop is sized so "the leak, if back, is gigabytes"; the
residual that was there is 16 B per character, and 16 B/char is
indistinguishable from zero at a size that would catch 150 B/char. Now that the
subscript stops allocating, the case passes at 60 MB with room to spare (1.6
MB), and that is the moment the number is revisited.