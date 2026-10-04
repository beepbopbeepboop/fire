# FORMAL_eq_dispatch_two_call_operands_are_not_a_frame_address: `mk(1) == mk(2)` answers "same object" where the source's `__eq__` answers True

**Status 2026-10-03 (`work/formal13-4`): the SILENT WRONG ANSWER is FIXED on both
architectures — edits 1 and 2 of "The exact next step" landed, with a test on each
— and edit 3 did NOT, for a reason this section measures.**

| program | CPython | arm64 | x86-64 | |
|---|---|---|---|---|
| `b` | `True` | **1** | **1** | was `0`: builds, runs, exit 0, nothing on stderr |
| `c` | `True True` | REFUSED | REFUSED | unchanged; the reason is below and it is not the one this document guessed |

Pinned by `test_formal_run.py`'s `both_arch_eq_dispatch_through_two_call_operands`
(the plain-`struct` spelling, built and RUN on both backends, `eq=1`) and by
`test_dataclasses_formal.py`'s `a_user_declared_eq_reaches_the_method_through_two_call_operands`
(the `@dataclass` spelling, against CPython). Both were measured red before the
change and green after it.

**What landed, in `formal/build.py`:**

1. **The guard.** `_rewrite_eq_on_frame_receivers`'s `if not hs and not
   fn_one_word: continue` now also consults `_call_frame_structs` — as
   `_fn_comparison_call_frame(fn, …)`, one walk per FUNCTION rather than per node,
   because the guard needs the answer before the loop and the loop needs the same
   one, and two walks of "which call operands settle" is the pair that agrees
   until the day one of them is edited.
2. **The audit's fourth shape.** `_own_eq_class_touching` now recognises a
   `CallExpr` that `model.call_result_frame_struct` settles to one of the `own`
   structs, from the same table `_eq_dispatch_call` decides from. That turned a
   second silent wrong answer into a refusal: `printf("%d", mk(1) == 5)` printed
   `0` where CPython prints `1`, and the audit said nothing because a call to a
   function is not a construction, a frame candidate or a one-word candidate. It
   is now refused by name, and `_own_eq_gap` was taught not to blame the `mk(1)`
   — "a call the dispatch CAN resolve is not a gap", since the first version of
   that refusal said "mk(...) is a construction", which is false in every clause
   and sends the reader to edit the wrong operand. Pinned by
   `a_user_declared_eq_against_a_word_names_the_word_not_the_call`, whose fourth
   column forbids that sentence.

**Why edit 3 did not land, and what it actually is.** The document's guess was
"the recognition does not reach the OTHER argument position". It does — the
position is not the problem, and `_frame_valued_calls` is position-blind by
construction as this document says. The measurement is that `_frame_valued_calls`
records NOTHING for the `mk(1)`/`mk(2)` call sites at all, in either program:

    $ python3 .tmp/dbg.py build --formal --no-prove -o .tmp/ow/dbg .tmp/ow/c.mojo
    FRAME_CALLS main [(4468538096, (['Always'], 'a Always frame built here'))]
      CALL 4472356944 Always(...)          ← the only one: the construction
      CALL 4472357264 mk(...)              ← absent
      CALL 4472341776 mk(...)              ← absent

and the reason is one clause upstream of this document's whole subject:
`formal/build.py::_frame_return_status` recognises a frame-valued `return` in
exactly TWO ways — a bare name holding a frame, and a call to a function already
known to return one — and `mk` is `def mk(v: int) -> Always: return Always(v,
v + 1)`, whose return value is a CONSTRUCTION. So `mk` is classified
`_RETURN_WORD`, every caller reserves no block for its result, and nothing about
the call can be recognised as a frame anywhere. Filed, with the measurement and
the blocker, as `bugs/FORMAL_a_function_whose_return_value_is_a_construction_is_not_frame_returning.md`.

`c` is therefore unchanged and still refused by name, which is the safe direction,
and `b` — the silent wrong answer this document is about — is fixed.

**Status (original, 2026-10-03, `work/merge-formal8`): OPEN, measured on both
architectures, and it is a SILENT WRONG ANSWER
rather than a refusal. Found while merging `work/formal8-5`, `work/formal8-1`
and `work/formal8-4` into `work/merge-formal8`, on the tree that
carries all three. It predates the merge: the two sites named below are
`work/formal8-5`'s, unchanged by any of the three merges.**

This is the residue `bugs/FORMAL_eq_dispatch_on_a_frame_receiver.md` says its
own §1 was measured against — "a bypass for one that declares `__eq__`" — one
shape further on. That document's call-operand work landed
`a == mk(1)`, and its pinned test
(`eq_operator_reaches_a_declared_eq_through_a_call_operand`) puts `var t = mk(1)`
in the same function, which is what makes that case work. The shape below is
the same feature with the one thing that made it work removed.

## What I ran

Two programs, `--formal --no-prove`, both backends, run and compared against
CPython on the same text. `.tmp/ow/b.mojo`:

```python
from dataclasses import dataclass

@dataclass
class Always:
    x: int
    y: int

    def __eq__(self, other):
        return True

def mk(v: int) -> Always:
    return Always(v, v + 1)

def main(n):
    printf("%d", mk(1) == mk(2))
    return 0
```

and `.tmp/ow/c.mojo`, which is the same plus one binding in `main`:

```python
def main(n):
    q = Always(0, 0)
    printf("%d %d", mk(1) == mk(2), q == mk(2))
    return 0
```

## What I saw

| program | CPython | arm64 | x86-64 | |
|---|---|---|---|---|
| `b` | `True` | **0** | **0** | builds, runs, exit 0, nothing on stderr |
| `c` | `True True` | REFUSED | REFUSED | `frame_holder_disagreement_refusal` |

`b` is the bug: `Always.__eq__` returns True for everything, the image prints
`0`. An address compare answers "are these the same object", and two `mk`
calls are two objects. Nothing on either backend says anything.

`c` is loud and therefore not this bug — but it is the SAME subject and it is
why the fix cannot be "just relax the skip":

```
Always___eq__() takes a Always receiver at argument 0 — 'self' — at
Always___eq__(q, mk(2)) here, and something that is not a frame address at
Always___eq__(mk(1), mk(2)). One parameter, two kinds of value …
```

`mk(1)` at that call site IS a frame address — it is the declared return type
of `mk`, which is `Always`. So `b`'s operator needs rewriting into a call, and
the moment the rewrite fires the holder check sees `mk(1)` where it cannot
recognise a frame.

## What I expected

`1` on both architectures, from `Always___eq__(mk(1), mk(2))`. The class's own
method says True for any operands and `test_dataclasses_formal.py`'s
`a_user_declared_eq_reaches_the_method` already pins that this backend reaches
that method — just not from two call operands.

## Why `b` is not rewritten

`_rewrite_eq_on_frame_receivers` (`formal/build.py`) opens its per-function
loop with

```python
if not hs and not fn_one_word:
    continue
```

and `main` in `b` has neither: it binds nothing, so no frame construction or
frame-returning call in it puts a name in the holder table. The loop never asks
`_eq_dispatch_call` about the comparison, so the operator stays an address
compare. That guard is right for what it was written for — a function with no
frame-valued name has no comparison it could dispatch — and it is now one
predicate too coarse, because after the call-operand work a frame operand can be
a CALL that `model.call_result_frame_struct` settles from the callee's declared
return type, with no name involved at all.

Measured to be exactly that guard and not the dispatch: adding one unrelated
`q = Always(0, 0)` to `main` (program `c`) takes the guard past, the rewrite
fires, and the build then fails on the holder check instead — which is the
second half.

## Why the audit does not catch `b` either

`formal/build.py::_check_own_eq_dispatch` is the check whose stated purpose is
this exact failure — "the residue of that day is a program that answers 0 where
the source's own `__eq__` says True" — and it does not fire on `b`.

Its recogniser, `_own_eq_class_touching`, answers "is this operand a value of
an own-`__eq__` dataclass" from three shapes: a CONSTRUCTION (`isinstance(side,
F.CallExpr)` with `side.func.name` in the class names), a NAME in the frame
candidate table, or a NAME in the one-word table. A call to a FUNCTION is none
of the three, and `mk` is not a class name. So `mk(1)` is invisible to it, in
exactly the case where the rewrite has just failed to fire.

`FORMAL_dataclass_own_eq_is_still_refused_though_dispatch_works` (deleted
by `work/formal8-4` with its fix) measured the audit at 0 of 13 and this is the
row it did not have. Note the audit does fire when the rewrite has ALREADY
replaced the comparison node — it cannot see it, which is the safe direction —
so this hole is precisely the rewrite's hole.

## Exact next step

Three edits, in `formal/build.py`, and the order matters because the third is
what the first two expose:

1. **Teach `_own_eq_class_touching` the fourth shape**: a `CallExpr` whose
   `model.call_result_frame_struct` settles to one of the `own` structs. That
   reuses the same interprocedural answer the rewrite uses, so the audit and the
   rewrite agree by construction rather than by two recognisers agreeing.
2. **Relax the `if not hs and not fn_one_word: continue` guard** to also skip
   past a node that has a call operand `call_result_frame_struct` settles —
   i.e. ask `_call_frame_structs` before deciding there is nothing to ask.
3. **`_check_holder_agreements` must then see `mk(1)` as a frame address**, or
   `c` above is refused. `_argument_is_frame_address` covers argument 0 (the
   chain case in `FORMAL_eq_dispatch_on_a_frame_receiver.md` §1) through
   `_frame_valued_calls`, and `c` says the recognition does not reach the OTHER
   argument position. `_frame_valued_calls` is `{id(call): ([struct name], why)}`
   — position-blind by construction — so the first thing to check is whether
   `struct_returned_frame_sites` records `mk(1)`/`mk(2)` at all for a callee
   that is only ever a comparison operand, before assuming the position is the
   problem.

No Lean is needed for any of the three; the oracle is CPython on the same text,
which is what `test_dataclasses_formal.py` already runs.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend arm64 \
      -o .tmp/nb .tmp/ow/b.mojo && .tmp/nb      # 0
$ python3 -c "
from dataclasses import dataclass
@dataclass
class Always:
    x: int
    y: int
    def __eq__(self, other): return True
def mk(v): return Always(v, v+1)
print(mk(1) == mk(2), end=' ')"                   # True
```

## Not in a test, and why

A row asserting `0` would make a known-wrong answer the expectation, which is
what `FORMAL_one_word_eq_dispatch_stops_at_a_call_boundary` declines to
do for the same family and for the same reason. The measurement belongs here
until the answer is 1.