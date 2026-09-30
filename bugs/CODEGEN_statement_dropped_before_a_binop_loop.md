# BUG: a statement is silently DROPPED from the generated C when a `for` body contains a binary op on its loop variable

**State: OPEN — not fixed, no code change.** Found 2026-09-29 while working
`bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md`. Pre-existing and
independent of that work; filed because a statement that compiles to
nothing is the worst outcome in this repo's ranking (right answer,
garbage, wrong answer, refusal, **no answer at all with exit 0**), and
because a future session chasing a "my output has a missing line"
symptom deserves the measurement rather than the re-derivation.

## The repro

`.mojo`, compiled through `gimple_codegen.compile_to_gimple` + `gcc
-fgimple` + `runtime/fire_runtime.c`:

    fn main():
        var t = struct.unpack('<if', struct.pack('<if', 1, 1.5))
        var i = 1
        print(t[i])
        print(t[i] + 1)
        print(t[i] * 2.0)
        print(str(t[i]))
        print(f"{t[i]}")
        print(t[0] + 1)          # <-- THIS STATEMENT PRODUCES NO C AT ALL
        var a = [1, 2.5]
        for x in a:
            print(x + 1)

## What I saw

    4609434218613702656
    4609434218613702657
    9.218868437227405e+18
    4609434218613702656
    4609434218613702656
    1.0
    3.5

Six prints and two loop iterations, exit 0. `print(t[0] + 1)` should have
printed `2` and printed nothing. Confirmed by reading the generated C: the
`#line 9` block is **absent from `_gimple_main` altogether** — not
mislabelled, not unreachable, not inside the loop; not there.

CPython, on the same program, prints eight lines: `1, 2.5, 3.0, 1.5, 1.5,
2, 2, 3.5`.

## It is pre-existing

Re-derived on `10023b8` (master's tip when this was found) in a scratch
`git archive` of that commit: identical output, and the same missing
`#line 9` block in the generated C. It is therefore NOT a regression from
the per-slot-kinds work on `work/hard-struct-kwargs`, and that branch's own
`test_gimple_runner.py` run (175/175) does not reach it.

## How narrow it is — and how not

Every one of these does NOT reproduce it (all measured on `10023b8`):

- any one of the six statements removed (5 of the 6 printed, then the
  `t[0] + 1` line, then the loop, is fine for all six 5-subsets);
- the loop body's `print(x + 1)` changed to `print(x)` (fine);
- the loop's iterable inlined as `for x in [1, 2.5]:` (fine);
- the loop's iterable a homogeneous local `var a = [1, 2]` (fine);
- any trailing statement after the loop (fine);
- a binary op in a loop body with a plain int list and no `struct` at all
  (`print(1); var a = [1, 2]; for x in a: print(x + 1)` — fine);
- seven `print`s before a `for x in [1, 2.5]:` loop (fine).

So it needs the whole combination: a `struct.unpack` result of a MIXED
format, at least five preceding statements including both a `str()` and an
f-string over that result, a heterogeneous list literal bound to a local,
and a `for` over that local whose body does arithmetic on the loop
variable. I did not get it down past that, and I would not trust a
hypothesised mechanism I have not read out of the emitter.

## Where I would start

`mojo/backend_gimple/emit_loops.py`'s `_gen_for_list` emits
`bb_cond`/`bb_body`/`bb_post`/`bb_after` through `gen._new_bb()` and
`gen._emit()`, and the body's arithmetic goes through `_lower_binary`
(`emit_exprs.py`). The statement before a loop is lowered by
`gst.gen_stmt` into the same `gen` buffer, so a buffer/`_line` bookkeeping
bug in the loop path that RESETS rather than appends would drop exactly the
preceding block and leave every BB label intact. That is a guess to check,
not a finding: the generated C's `#line` markers and `bb_*` labels are all
well formed, so whatever is wrong happened before emission (an AST walk
that skipped the node) rather than in it.

The two shapes worth trying first, because they are the ones that changed
the answer: `mojo_gimple`'s `_calls_in_stmts` memo cache
(`gen._calls_in_stmts_cache`, keyed by `id(stmt)`, documented in
`gimple_codegen.py` as safe because "the traversal reads no mutable gen
state and every consumer only READS the collected nodes") — a cache that
does get poisoned by lowering would show up exactly like this, as one
statement's lowering being reused or skipped; and the `t[0]` STATIC-index
subscript, which is the one read in the dropped statement that has a
compile-time slot index and so takes a different path from every `t[i]`
around it.

## Note for whoever takes it

`bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md` is where the
`struct` half of this sits, and it is not on that doc's residue list: the
statement dropped here is dropped identically before and after the
per-slot-kinds work. Do not close that doc on this.
