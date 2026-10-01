# FORMAL_eq_dispatch_on_a_frame_receiver: `a == b` reaches a declared `__eq__`, and what it still does not reach

**Status: the multi-field-frame case is FIXED and measured before and after on
both architectures.** The reproducer in
`bugs/FORMAL_eq_does_not_dispatch_to_a_user_dunder.md` (filed on
`work/merge2-formal`) is closed; this document records what landed, the part of
the filing whose stated premise did not survive re-measurement, and the three
shapes that are still wrong answers — none of which is reachable through the
table the fix uses, and each of which is named here so the next session does not
have to rediscover that they are open.

---

## What landed

`formal/build.py::_rewrite_eq_on_frame_receivers` and
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

## The three shapes still wrong, and why the table cannot reach them

All three measured on this tree, both architectures, and all three are
PRECIOUS wrong answers rather than refusals — which is why they are written down
rather than left.

1. **A ONE-FIELD struct's local.**  `class P: var x: Int` with
   `__eq__` returning True: `a == b` answers the word compare of two field
   values (0) where CPython says 1.  `struct_is_framed` is False for a one-field
   struct, `_frame_receivers` is entered over `framed` names only, so `a` is
   not in `holders` and no candidate list exists for it.  The missing thing is a
   `{name: struct}` table for a construction whose result is ONE WORD — the
   mirror of `hstruct`, keyed on what a one-word constructor binds rather than on
   what a frame constructor binds.  **Next step:** publish it beside
   `fn._frame_candidates` in `_frame_receivers` (from `_constructor_bindings` over
   the NON-framed structs, which is the same enumeration one filter wider) and
   read it in `_eq_dispatch_call` when `hs` has nothing to say.  The safety
   argument is the one that makes this rewrite safe at all — both operands must
   be frames of the same struct — and it is stated once, in
   `_rewrite_eq_on_frame_receivers`'s docstring, so the second reader inherits
   it.

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