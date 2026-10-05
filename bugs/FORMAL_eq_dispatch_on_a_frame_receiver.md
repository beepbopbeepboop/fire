# FORMAL_eq_dispatch_on_a_frame_receiver: what `==` still does not reach

**Status: shapes 1 and 2 of "the two shapes still open" are now measured and
CLOSED, and the one that remains is a value-model limit rather than a rewrite.**
What landed first (the shape-1 `a == b`/call-operand work and the second defect
it uncovered) is recorded below so a reader does not re-open it; §"The shape that
remains" is what is left.

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

### 0. FIXED (`formal29-2-r2`): a chain with a CALL in the middle

`t == mk(1) == u` is the shape the previous status called "deliberately left
alone". **It is fixed, and at the layer the old text named** — a
statement-level rewrite, `_hoist_eq_chain_middle_calls`
(`formal/build.py`), which binds the operand once in the statement that contains
the chain.

The defect it removes is exactly what the old §2 said, with the mechanism added:
`F.CompareChain` says *each of `operands` is evaluated exactly once* (it is in
the node's own docstring, which is the language's rule and not this document's),
and the dispatch lowering turns the chain into the `and` of its links, in which
the middle operand appears in TWO of them:

```
a == mk(1) == b   →   A___eq__(a, mk(1)) and A___eq__(mk(1), b)
```

so the callee runs twice. The rewrite declined the shape rather than emit it
(`lowered = False` at index `i > 0`), the operator stayed an ADDRESS COMPARE, and
that is a silent wrong answer rather than a refusal: measured, both
architectures, `t == mk(1) == mk(1)` printed `chain=0` where CPython prints 1,
because `mk(1)` builds a second object and an address compare asks whether it is
the first.

Three things the fix is, and each of them is a way it could have been wrong:

* **A hoist, not a guard.** The chain is an EXPRESSION, so the temporary has to
  be bound in the enclosing statement — which is the statement-level rewrite the
  old next step asked for, and why `_rewrite_stmt_lists` (the same function
  `with` lowering uses) is the mechanism. One `CompareChain` node holds ONE node
  per operand, so replacing `operands[i]` reaches both links: the call is
  evaluated once and both reads are the same read.
* **INSIDE the fixpoint, not in front of it.** The temporary is a frame holder
  only once the holder analysis has seen the binding, so the pass runs in
  `_frame_receivers`' round loop and its count joins the progress the loop tests.
  It introduces no dispatch decision — that is still `_rewrite_eq_on_frame_
  receivers`' alone, one round later, from the tables — which is the constraint
  the old text named.
* **ONLY a call that dispatches.** `model.call_result_frame_struct` has to name
  the struct from the callee's declared return type; an unannotated callee
  answers None and nothing is hoisted.

Measured after, both architectures, against CPython on the same text: `mid=1
diff=0 ends=1 chain3=0`, where `mid` is True only if the method ran and `diff`
False only if it ran on the values. The nested shapes are pinned too, because
each is a way a hoist is wrong on ONE architecture and the single-statement row
cannot see them: the binding inside a `while` body (`hits=3`, so it re-evaluates
per iteration the way the expression did — a hoist to the function top answers
1), a source local spelled `_eq_operand1`, which is the name the hoist hands
itself (`coll=7`), and a chain in a `return` statement, where the enclosing
statement has to be SPLIT rather than filled in.

**The evaluation ORDER this changes, stated because it is real:** `a == f() == b`
runs `f()` between the two links' left operand reads, and the hoist runs it
before the first link. That is observable only if `f()` mutates something the
first link's `__eq__` reads, and it is the price of a temporary rather than a
choice: with no name to hold the value the alternatives are calling it twice
(what the language does not say) or leaving the comparison an address compare
(what this did). It is written down in the pass's docstring rather than left to
a reader of the diff.

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

**Re-measured for this status, because the two halves are not the same verdict
and only one of them is a limit.** `s == None` and `s == 5` are not the same
shape as `a == b`: a frame address is never 0 and never 5, so the operator the
lowering leaves there answers False, which is CPython's answer for both (no
declared `__eq__` means the inherited identity comparison, and the fallback after
`NotImplemented` IS identity). **Those two are correct as they stand and are not
work.** `a == b` across two structs is the whole of what remains, and it is
refused.

**What a middle call to an UNANNOTATED callee is, since the middle-call fix now
touches it:** `t == un(1) == un(1)` with `def un(v): …` and no return type stays
an address compare and answers 0 where CPython answers 1. That is the same limit
as `t == un(1)` **at either end of a chain**, which the call-operand work left
alone too, and it is not refusable: the path cannot tell whether the callee
returns a struct at all, so a chain whose operands are three integers would look
identical, and refusing it would refuse correct programs. It is a limit of the
call-operand rule ("the callee's own DECLARED return type, and nothing else"),
not a gap in the hoist, which is why the hoist declines it by the same test the
dispatch does.

### 2. FIXED — see §0 above

`t == mk(1) == u` was "the one shape the call-operand work deliberately leaves
alone". It is bound to a temporary now. What the old next step prescribed —
*bind the operand to a temporary in the enclosing statement before rewriting, as
a statement-level rewrite with its own round in `_frame_receivers`' fixpoint* —
is what landed, and the constraint it named is what the pass respects (it
introduces a store and no dispatch decision).

### 3. What was NOT re-measured

The `==`/`!=` rows above are real builds and runs on both architectures, in
`test_formal_run.py`. The **sweep** was not re-run — a whole-tree sweep is not a
light worker's — so "nothing that answered before is refused now" rests on the
narrow suites, and not on a class-by-class sweep diff. The direction of risk is
the one that matters, and the hoist adds one more: it introduces a LOCAL into a
body the holder analysis has not read yet, so the round after it re-derives the
holder tables over a function with one more binding in it — which is also why it
is counted as progress rather than run once. The suites behind this status:
`test_formal_run.py`'s 159 rows over the eq / both-arch / cross-module /
by-reference / returned-frame / conditional-arm groups (0 fail), and
`test_formal_returned_frame.py` 46, `test_formal_frame_len.py` 10,
`test_formal_cross_module.py` 35, `test_formal_toplevel.py` 116,
`test_formal_method_param_field.py` 28, `test_formal_value_model.py` 82.

`test_struct_formal.py` is RED on this tree and was red before this change, for
a reason with nothing to do with it: `from struct import calcsize` is refused by
`formal/hostmods/os/_syscalls.mojo`'s own string-subscript rule
(`d[i]` on a string whose text is not ASCII — a documented limit in
`bugs/FORMAL_string_value_model.md`, and that module's docstrings are full of
em-dashes). Recorded here because the old status listed that file among the
suites this claim rests on, and a reader who re-runs it deserves to know which
of its 163 failures are theirs.
