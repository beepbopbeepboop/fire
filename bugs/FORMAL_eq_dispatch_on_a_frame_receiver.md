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

## Status, 2026-10-05 (`formal31-3`): the remaining refusal was RIGHT and its
## REASON was false, and following the advice could not have fixed it

§1 says of `a == b` across two structs: *"It is REFUSED rather than left wrong,
because `_eq_dispatch_call` sees two candidate lists that do not settle on one
struct — which is the correct verdict for the wrong reason, and the message
(`compares two FRAME ADDRESSES … does not settle it`) says so."*

**It did not say so. The message named a reason that is false about half the
shapes that reach it, and its advice could not work.** Re-measured, both
architectures, on the reproducer the section above already describes:

```mojo
struct A:
    var x: Int
    def __eq__(self, other: A) -> Bool:
        return self.x == other.x
struct B:
    var x: Int

def main(n):
    var a = A()
    a.x = 1
    var b = B()
    b.x = 1
    if a == b:            # CPython: True.
        return 1
```

```
build: a == b compares two FRAME ADDRESSES, so the answer is the frame's own
struct's `__eq__` — which means WHICH struct is the whole of the question, and
A, B does not settle it: A declares one; B declares none. Each name holds a
different frame on each path that binds it, and this analysis has no path
sensitivity to say which one is live at this comparison, …  Give each name one
binding, or give every candidate the same `__eq__`
```

Every clause of that tail is wrong for this program:

  * **`a` and `b` are each bound once.** There is no path, so "no path
    sensitivity" is not the obstacle.
  * **"Give each name one binding"** is impossible — each already has one.
  * **"Give every candidate the same `__eq__`" makes it WORSE, and this is the
    part that matters.** `model.struct_dunder_dispatch_candidates`'s decision is
    `if len(owners) > 1 or have != len(rows): refuse`, so a `B` that declares a
    `__eq__` too puts two names in `owners` and takes the `len(owners) > 1`
    arm — the same refusal, with the same message, forever.

A reader who follows this message is sent after a non-bug, which
`formal/model.py`'s own note on `FRAME_KIND` calls the expensive direction and
`test_refusal_taxonomy.py` is the standing check for. **This is a defect in its
own right**, independent of the `NotImplemented` work the section defers.

### What landed

`model.eq_dispatch_candidates_disagree` now takes the two per-side candidate
SIZES (passed by `formal/build.py::_eq_dispatch_decide`, which already has both
lists) and answers in **two messages for two different facts**:

  * **a NAME IS NOT PINNED** (`left_count > 1` or `right_count > 1`) — the
    existing text unchanged, because it is exactly right: which struct is live
    depends on the path, and giving each name one binding does settle it.
  * **EACH SIDE IS PINNED AND THEY ARE DIFFERENT STRUCTS** (`1` and `1`) — a new
    text that says there is no path to be insensitive to, names CPython's
    REFLECTED dispatch as the reason (`A.__eq__(a, b)` is handed a `B`, which is
    not a well-typed call in Mojo; CPython's answer is `NotImplemented`, which
    asks the other operand's `__eq__` and falls back to identity), says the
    representation for that is absent, **says explicitly that changing the
    bindings will not fix it and that giving both structs a `__eq__` will not
    either — two owners is the case that refuses** — and then says what a
    program CAN do: compare the fields, or make the two sides the same struct.
    It ends with this document's path, so the next reader arrives here.

### The tests

`test_formal_value_model.py`'s `REFUSALS` already had one row per shape, and its
needles were the SHARED opening clause and `"does not settle it"` — which is to
say both rows passed whichever message the rule produced. They are now the two
halves of the split, which is what pins it:

| row | needle |
|---|---|
| `one_name_two_candidate_structs_is_refused` | `no path sensitivity to say which one is live at` |
| `two_structs_only_one_with_a_dunder_is_refused` | `CPython's REFLECTED dispatch` |

Both on both architectures (that is what a `refuse:` row in this file asserts),
**83/83 in `test_formal_value_model.py`**, and the eq family in
`test_formal_run.py` is unaffected — `eq_operator_reaches_a_declared_eq`,
`eq_no_declared_dunder_stays_identity` and
`eq_chain_with_a_call_in_the_middle_reaches_a_declared_eq` all still pass, which
is the control that says the split did not move the DECISION, only the wording
of one of its two refusals.

The stale clause in that table's header comment — *"The pre-change tree answered
both of them with a flag-setting compare of two addresses and no diagnostic"* —
is corrected in place: `cross_struct` did get a diagnostic, it was just
half-written.

### What is STILL open, and it is the same thing

`NotImplemented` as a dunder's return value is a value-model change shared with
the Lean proof, and nothing here is a step towards it: `a == b` across two
structs is refused before and after, on both backends, with a message that now
says why. §3's standing caveat is unchanged — the sweep was not re-run, so
"nothing that answered before is refused now" rests on the narrow suites
(`test_formal_value_model.py` 83, `test_formal_run.py`'s eq rows,
`test_formal_returned_frame.py` 46, `test_formal_method_param_field.py` 32).
