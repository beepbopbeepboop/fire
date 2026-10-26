# FORMAL_a_fold_over_a_blob_needs_a_proof_model_and_not_only_codegen

**Claim** `project:builtins-conformance` on `work/formal62-builtins-conformance`.
**Status: OPEN, and NOT a small piece of work.** Nothing here is filed as a bug
in the sense of "a wrong answer reached a user"; it is a measured statement of
what lowering `sum`/`any`/`all`/`min`/`max` over a container would COST, written
down because the cost is the interesting part and because the obvious
implementation would make the proving path worse.

**The measurement.** `test_formal_builtins_conformance.py`'s `folds` group
holds eight cases and every one is a refusal today:

    var xs = [1, 2, 3]          # CPython: 6
    printf("L%lld\n", sum(xs))  # this path: refused, by name

    var xs = [1, 1, 0]           # CPython: 0
    printf("L%lld\n", all(xs))  # this path: refused, by name

The refusal is the model's own row and is CORRECT as a statement about this
backend: `NOT_LOWERED_BUILTINS`'s `sum` row says "a fold over a sequence, the
same shape as `all`", and its `all` row says "a fold over a sequence with a
short circuit, which is a run-time sequence this one-word value model cannot
carry". A `run`-time sequence is not a value here — every value is one 64-bit
integer word, or a frame address, or a `char *` to interned literal bytes.

**WHY IT IS NOT A ONE-LINE ADD, which is the part worth recording.** A blob IS
already `[count][e0…]` with its count in the first eight bytes, and
`len(blob)` is already one load from offset 0 on both backends
(`model.len_operand_lowering`'s `LEN_FROM_BLOB_FIELD`). So the CODEGEN half looks
like a loop: load the count, walk the elements, add or branch, and the answer is
ONE WORD — the same word every other value on this path is. That is why these
five are the first of the refusals worth attacking, and `test_formal_builtins_
conformance.py`'s `folds` group note says so.

But codegen is the cheap half. The PROOF half is not, and landing codegen alone
would turn a clean refusal into a WORSE failure:

    formal/arm64_proof_gen.py:712 (and its x86-64 twin)
        raise NotImplementedError(
            f"model: call to `{sym or '?'}` has no model in this image (an "
            f"extern, or a function this generator emits no `_go` for); "
            f"refusing rather than inventing its return value")

`fire.py build --formal` PROVES by default, and the proof generator raises for
any call it has no `_go` for. So a `sum(xs)` that codegen lowered would compile,
run, and answer 6 — and then fail to GENERATE A PROOF. `formal_sweep.py` and
the corpus both build with proving on, so this would be a regression measured in
files rather than in one program's exit status: every `sum`/`any`/`all` call in
the sweep that is today a clean, classified refusal would become a
`backend-crash`. That is strictly worse than the refusal it replaced, and it is
the reason this document exists instead of a patch.

**WHAT THE PROOF HALF NEEDS**, as far as it was measured:

  * a `_go` definition for the fold in the proof layer — a function over the
    blob's base address and its count, in the same vocabulary `lib/ProofLib.lean`
    uses for `fdiv64`/`frem64` and for whatever already models a container walk.
    `formal/model.py`'s TEXT ENCODING block and `bugs/FORMAL_a_specification_
    layer_that_stops_at_a_finite_range.md` are the two places to read first;
  * a LOOP CONTRACT. A fold is a loop over a run-time count, and this backend
    has a measured history of getting the loop contract wrong rather than
    absent: `bugs/FORMAL_a_range_loop_contract_states_the_unsigned_order_
    against_a_signed_flag.md` and `bugs/FORMAL_a_loop_that_is_neither_a_decrement_
    nor_a_range_loop_has_no_contract.md` are two shapes of the same gap, and
    the ladder's reach was a third shape of the same gap, and `f801d013` closed
    it (its doc is deleted; the measurement is still the one a reader wants, so
    it is named here). A fold's
    accumulator is loop-carried state, which is the hardest of the three;
  * the same on BOTH backends, since a proof that exists for one architecture and
    not the other is a census row that reports a construct as covered on one and
    not the other.

**THE NEXT STEP, in the order it should be done**, and the order is the whole of
this document:

  1. Land the PROOF model for a fold first, with no codegen change, and watch
     the proof census move. A proof that exists and is never demanded is inert
     and cheap; codegen without it is a regression. If step 1 turns out to be
     blocked on `formal/specs.py`'s expression language not carrying a fold at
     all, that is the finding, and it is the one worth having.
  2. Then `sum` alone, on arm64, over a list blob whose element kind is `int`
     (which `model.kind_of`'s `SliceExpr`/`Comprehension`/`range` arms all
     already classify, so the operand is settled).
  3. `any` and `all` next: they are the same loop with a short circuit, and the
     short circuit is a mid-loop exit whose proof obligation is the contract
     ladder's, not the fold's.
  4. `min(xs)`/`max(xs)` LAST and possibly never, because their table rows are
     already partly untrue in a way the others' are not: two or more positional
     arguments ARE lowered (`formal/build.py::_lower_builtin_extremum`), so a
     `max` row that says "not lowered" is a statement about three specific
     shapes and any implementation has to keep the row honest about which. The
     one-argument form is a fold with a compare-and-select per element, and the
     emitters already have both halves.

**WHAT IS NOT NEEDED, so nobody re-derives it.** `zip`, `enumerate` and
`reversed` are NOT in this document's scope and are not blocked by the proof
layer's absence of a fold model: their answers are a pair or a run-time-sized
container, which `FORMAL the value model is one word` and
`bugs/FORMAL_listdir_no_run_time_sequence.md` are about, and no fold model
changes that. `sorted`, `map` and `filter` are blocked by a different wall
entirely — a call THROUGH A VALUE per element, since a value here has no code
address in it — and are not reachable by any amount of fold work.

**THE COVERAGE THAT EXISTS TODAY, so this is not an unmeasured claim.**
`test_formal_builtins_conformance.py` holds all eight fold shapes plus
`min(xs)`/`max(xs)` with a `key=` and a `default=`, runs each on BOTH backends,
and requires the refusal to NAME the builtin — so a day when one of them starts
answering, the table goes red rather than the corpus quietly changing class.