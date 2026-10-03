# FORMAL_eq_dispatch_on_a_frame_receiver: what `==` still does not reach

**Status: shape 1 FIXED (2026-10-02, the previous worker), the CALL-operand
shapes FIXED (2026-10-02, `work/formal8-5`), and shapes 2 and the chain's middle
still open.** What landed is recorded below so a reader does not re-open it; what
is left is the two sections at the bottom, and both of them are the same limit
wearing two spellings.

## What landed: a comparison whose operand is a CALL

The frame case's whole safety argument is that both operands are frame ADDRESSES
of the same struct, and it was settled by asking the holder table — which is
keyed by NAME. An operand that is a call was therefore never asked about, and
the operator stayed a flag-setting compare of two words, which answers "are
these the same object": CPython's inherited `object.__eq__` for a struct that
declares none, and a **bypass** for one that does. Measured, both architectures,
on a field-wise `__eq__` and two DISTINCT objects with equal fields:

```mojo
struct A:
    var x: Int
    var y: Int

    def __eq__(self, other: A) -> Bool:
        if other.y != self.y:
            return False
        return self.x == other.x

def mk(v: Int) -> A:
    var a = A()
    a.x = v
    a.y = v
    return a

def main(n: Int) -> Int:
    var t = mk(1)
    if t == mk(1):        # CPython: True.  This path, before: False.
        return 7
    return 0
```

Nothing refused it, on either backend, and nothing on stderr said anything.

The struct is now read off the callee's own **declared return type**
(`formal/model.py`'s `call_result_frame_struct`, the shape `_rhs_pointee`
already uses to read a callee's return annotation for a POINTER — an
interprocedural fact, not an inference). `!=` follows the same path and negates
the same way it always did. Pinned by `test_formal_run.py`'s
`eq_operator_reaches_a_declared_eq_through_a_call_operand` (`eq=1 ne=0 diff=0`
against CPython).

**A chain's ends may each be a call, and its middle may not.** `mk(1) == t ==
mk(1)` is two links and each call appears in exactly one of them, so the call is
evaluated where the source put it. `t == mk(1) == u` is different: the chain
lowering reads each operand twice, so the same call appears in two links and
would be evaluated twice where the language evaluates it once. That shape stays
an address compare and is pinned at today's answer by
`eq_chain_with_a_call_in_the_middle_stays_an_address_compare` — see §3 below for
why it is not simply fixed.

### The second defect this uncovered, which is the more important one

Landing the chain needed a second fix, and the reason is worth recording because
it is a message that was false about the file. `_check_holder_agreements` sorts
every call site of a frame-valued parameter into "hands it a frame address" and
"hands it something else", and it recognised only the NAME spelling of the first
bucket. So the two `A___eq__` call sites in the chain — one with `t`, one with
`mk(1)` — were read as one of each, and the build refused with

```
A___eq__() takes a A receiver at argument 0 — 'self' — at t here, and
something that is not a frame address at mk(1).
```

`mk(1)` returns a frame. The check now asks `_argument_is_frame_address`, which
covers the other two spellings a frame reaches a parameter through — a
construction (`f(Pair(3, 4))`) and a call to a function that returns one
(`f(make())`) — by reusing `_frame_valued_calls`, **the table both emitters
build their blocks from**, rather than adding a third recogniser for "is this
call a frame". That check exists to stop a SIGSEGV (`frame_holder_disagreement_
refusal`'s measured program builds, runs and dies with exit 139), so it has to
be right about which words are addresses; a second implementation of the
recogniser would agree with the emitters until the day one of them was edited,
and the disagreement is a refusal lifted on a word that is not an address.

## The two shapes still open

### 1. A comparison against something that is not a frame of the same struct

`s == None`, `s == 5`, `a == b` where `a` is an `A` and `b` a `B`. Both operands
must be frames of the same struct, so none of these is rewritten and each stays
an address compare. `a == b` for two different structs is a wrong answer whenever
only one of them declares a dunder: CPython asks the right operand's `__eq__` when
the left one's returns `NotImplemented`, and this path has no representation for
`NotImplemented` to be returned as, so the reflected dispatch cannot be lowered at
all. It is REFUSED rather than left wrong, because `_eq_dispatch_call` sees two
candidate lists that do not settle on one struct — which is the correct verdict
for the wrong reason, and the message (`compares two FRAME ADDRESSES … does not
settle it`) says so.

**Next step: nothing narrow.** Lowering the reflected operand needs
`NotImplemented` as a third answer a dunder can return, which is a value-model
change shared with the Lean proof, not an operator-lowering one.

### 2. A chain with a CALL in the middle

`t == mk(1) == u` is the one shape the call-operand work deliberately leaves
alone, because the chain lowering re-reads every operand and a call in a middle
operand would be evaluated twice. **Next step: bind the operand to a temporary in
the enclosing statement before rewriting** — a statement-level rewrite, so it
needs its own round in `_frame_receivers`' fixpoint, and it must not introduce a
store in a pass whose contract is "one kind of value at every call site". The
two-round shape is the same one `_HOLDER_FIXPOINT_ROUNDS` already exists for (the
`S___eq__(a, b)` hand-off feeds the holder fixpoint through argument 1), so the
machinery is there; what is missing is a statement-level rewrite pass that owns
the enclosing statement, which this file does not have.

### 3. What was NOT re-measured

The `==`/`!=` rows above are real builds and runs on both architectures, in
`test_formal_run.py`. The **sweep** was not re-run — a whole-tree sweep is not a
light worker's — so "nothing that answered before is refused now" rests on the
narrow suites (`test_formal_run.py` 652 rows, `test_struct_formal.py` 174,
`test_formal_cross_module.py` 25, `test_formal_frame_len.py` 10) and not on a
class-by-class sweep diff. The direction of risk is the one that matters: the
new bucket in `_check_holder_agreements` can only turn a "plain" site into a
"frame" site, so it removes refusals (the chain) and adds one only where the two
sites genuinely disagree.
