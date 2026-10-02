# FORMAL_eq_dispatch_on_a_frame_receiver: `a == b` reaches a declared `__eq__`, and what it still does not reach

**Status: shape 1 of "The three shapes still wrong" is FIXED (2026-10-02);
shapes 2 and 3 are open and are restated at the bottom.** Measured before and
after on both architectures, in `test_formal_run.py`'s `EQ_DISPATCH_CASES`:

| program | before (arm64, x86-64) | after | CPython |
|---|---|---|---|
| one-field class, compared in the scope that bound it | `0` (exit 0) | `1` | `1` |
| one-field class, compared through a helper's ANNOTATED parameters | `eq=0 direct=1` | `eq=1 direct=1` | `eq=1 direct=1` |

**What landed.** `formal/build.py`'s `_one_word_constructor_bindings` and
`_seed_one_word_bindings`, a `{name: [struct]}` table for a name that is a
struct of ONE field's value — the mirror of `fn._frame_candidates` for the case
where there is no frame, which is what the doc's "next step" named. Two things
the doc did not foresee and which are worth writing down:

  * **The early return that owns this case.** `_frame_receivers` returns as soon
    as the module declares no FRAMED struct, publishing an empty contract — and a
    module whose structs are all one field is exactly that module, so the whole
    fixpoint, and with it the comparison rewrite, never ran. The arm now runs
    the one-word seeding and the rewrite and publishes the two tables empty,
    which is what they are.
  * **A parameter rebinding its own table's parameter.** `one_word =
    (one_word or {}).get(_fn_key(fn))` makes the SECOND iteration read the
    FIRST function's per-NAME table, so every function after the first looks
    empty and the rewrite silently did nothing for all of them. That is the
    whole reason the first attempt appeared to work on the reproducer (which is
    `main`'s own comparison) and did nothing for the helper-function spelling.
    The local is `fn_one_word`, and the comment says why.

An UNANNOTATED parameter is still not reached, which is the pre-existing
"a formal value carries no type" limit and not a gap in this: the new case's
helper annotates its parameters, and the comment says so.

---

**What landed before this (the multi-field-frame case), recorded here so the two
read as one document.** `formal/build.py::_rewrite_eq_on_frame_receivers` and
`formal/model.py::{dunder_receiver_method, struct_dunder_dispatch_candidates,
eq_dispatch_candidates_disagree}`.  `a == b` becomes
`Struct___eq__(a, b)` when both operands are bare names the holder analysis
believes hold a frame of the SAME single struct and that struct declares the
dunder; `!=` becomes `Struct___ne__` when the struct declares one and the
negation of the `__eq__` call when it does not, which is the language's own
fallback.  A CHAIN (`a == b == c`) becomes the short-circuiting `and` of its
pairwise comparisons, and only when every operand is a bare name.

It is the `len` rewrite's shape rather than a new mechanism, deliberately:
`_rewrite_len_on_frame_receivers` already answers "which struct's `__len__` is
this" from `hstruct` and `_receiverless_methods` already lowers a rewritten
method call through the ordinary call path, and `dunder_receiver_method` is now
the ONE predicate over a dunder's declaration shape that both use.  The two
differ in one place the filing did not foresee and which is worth stating
because it was the last thing standing between this and `self.x == other.x`:

**`S___eq__(a, b)` hands `b` to the method's SECOND parameter, so the rewrite
FEEDS the holder fixpoint.** The fixpoint was previously run to saturation once,
with the two operator rewrites after it, on the argument that each introduces
one edge (`Struct___len__` with a frame in argument 0) whose parameter is
already a holder.  That argument is true of `len` and false of `==`: without a
second saturation, `other` is not a holder, and every `__eq__` that reads the
field it was handed was refused by name — measured, and the message is the
pre-existing `model.field_access_refusal`:

```
build: Flag___eq__: 'other.x' is a field access through 'other', and this path
has no way to say what 'other' holds. … 'other' is bound here as a parameter,
so none of the three is established …
```

`self.x == other.x` is what an equality method is FOR, so a fix that stopped at
argument 0 would have converted every such program from a wrong answer into a
refusal.  `_HOLDER_FIXPOINT_ROUNDS` therefore runs saturate-then-rewrite until a
round neither grows a holder nor moves an operator, with a bound that RAISES
rather than the alternative, which is a hang in the compiler.

## Before and after, both architectures

Every row is a real build, run and compare.  CPython is the oracle and the
numbers are what it prints for the same text.

| program | before (arm64, x86-64) | after (arm64, x86-64) | CPython |
|---|---|---|---|
| `__eq__` returning True, `a == b` vs `a.__eq__(b)` | `eq=0 direct=1` | `eq=1 direct=1` | `eq=1 direct=1` |
| `!=` with only `__eq__` (True) | `ne=1` | `ne=0` | `ne=0` |
| `!=` with a `__ne__` returning False | `hne=1` | `hne=0` | `hne=0` |
| `self.x == other.x`, compared through a plain function's parameters | **refused** (`other.x`) | `r=1 back=0`, exit 7 | `r=1 back=0` |
| chain `a == b == c` on a field-wise `__eq__` | **refused** (`other.x`) | `chain=0 same=1` | `chain=0 same=1` |
| one name bound to an `A` or a `B`, only `B` declaring `__eq__` | **built**, address compare | refused by name, both backends | — |

## The premise in the filing that did not survive re-measurement

The filing said the fix needed "the agree-or-refuse over `fn._frame_candidates`
and the rule for 'the struct does NOT declare `__eq__`, so do not rewrite',
which is the half that keeps it from changing every comparison in the tree".  Both
halves are right and both are already how the code works; what the filing did
not say is that the second half is not a rule at all but the PRE-EXISTING
lowering being CORRECT.  A frame's address compare answers "are these the same
object", which is exactly what CPython's inherited `object.__eq__` answers, and
two live objects of one struct cannot share an address, so all three of `a == a`,
`a == b` and `a == c` (for two objects holding equal field values) are right
already.  `eq_no_declared_dunder_stays_identity` exists to hold that in place: a
rewrite that fired on every comparison would turn the third into 1.

## The three shapes, and where each one stands now

Shape 1 is FIXED (see the Status at the top). Shapes 2 and 3 are below,
unchanged and still open. All three were measured on this tree, both
architectures, and all three are PRECIOUS wrong answers rather than refusals —
which is why they are written down rather than left.

1. **A ONE-FIELD struct's local — FIXED.**  Landed as the Status describes:
   `_one_word_constructor_bindings` is the `{name: struct}` table this asked
   for, seeded in BOTH arms of `_frame_receivers` and read in
   `_eq_dispatch_call` where the holder test is.  The safety argument is the one
   this rewrite has always rested on — both operands must be values of the same
   single struct — and for a one-word struct it is a STRONGER statement than the
   frame case needs: there is one word in a one-field object, so two of them
   cannot be the same object, and a disagreement about which struct a name holds
   is the only question there is.  A name the holder analysis already
   classified keeps THAT answer even when the other operand is not a holder, so
   the mixed case is left exactly as it was.

2. **A comparison against something that is not a frame of the same struct.**
   `s == None`, `s == 5`, `a == b` where `a` is an `A` and `b` a `B`.  Both
   operands must be frames of the same struct, so none of these is rewritten and
   each stays an address compare.  `a == b` for two different structs is a WRONG
   ANSWER whenever only one of them declares a dunder: CPython asks the right
   operand's `__eq__` when the left one's returns `NotImplemented`, and this path
   has no representation for `NotImplemented` to be returned as, so the reflected
   dispatch cannot be lowered at all.  It is REFUSED rather than left wrong,
   because `_eq_dispatch_call` sees two candidate lists that do not settle on one
   struct — which is the correct verdict for the wrong reason, and the message
   (`compares two FRAME ADDRESSES … does not settle it`) says so.  **Next step:**
   nothing narrow.  Lowering the reflected operand needs `NotImplemented` as a
   third answer a dunder can return, which is a value-model change, not an
   operator-lowering one.

3. **A CHAIN with a call in an operand.**  `a.f() == b.g() == c.h()` is left
   alone, because the chain lowering re-reads the middle operands and a name read
   twice is the same load twice while an operand with a call in it would be
   called twice where the language calls it once.  **Next step:** bind the
   operands to temporaries in the enclosing statement before rewriting, which is
   a statement-level rewrite rather than an expression one and needs its own
   round in the same fixpoint.

## What the sweep does

Measured with `tools/formal_sweep.py --no-stdlib` before and after, on five
stdlib files that declare a comparison dunder and on the two repo files the
related docs name (`mlir.py`, `tools/procrun.py`): **identical verdicts, class
for class, on every one.**  All seven were already `codegen` or
`codegen/dependency` for unrelated reasons (a `String` frame address, a nested
`Atomic` frame, an unbound import chain), so nothing that answered before is
refused now.  The reverse direction is the real risk and it was checked: a file
can only move `PASS → codegen` if it compares two locals of a multi-field struct
whose class declares a dunder, and in the repo scope no `.py`/`.mojo` file
declares one at all (`type_system.py` is the only hit and it imports
`dataclasses`).

## Tests

* `test_formal_eq_dispatch.py` — the CPython ORACLE for this construct: it holds
  no expectations of its own, derives the CPython program from the same text, and
  requires each architecture's image to match CPython's stdout and exit status
  byte for byte.  7 cases, 6 of which fail on the pre-change tree (the seventh is
  the control that must not move) — measured against a clean `git archive HEAD`
  tree.
* `test_formal_run.py`'s `EQ_DISPATCH_CASES` — three of the same rows with fixed
  expected values, in the registered suite job, because a construct nothing in
  it exercises is a construct nothing in it can regress.

One measurement belongs here because the CPython oracle depends on it: **this
backend's string literals do not process `\n`.**  `printf("A[%d]\n", 7)` writes
`A [ 7 ] \ n`, twelve bytes and no newline, so a format string carrying an
escape makes the two engines disagree about bytes that have nothing to do with
the construct.  Every case prints one escape-free line for that reason.  It is a
separate defect from this one and is not fixed here.