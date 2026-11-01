# the specification layer states a refinement over a FINITE range, and the all-inputs claim is not attempted

**Area:** FORMAL, both backends — `formal/specs.py`, `lib/Specs.lean`,
`lib/ProofLib.lean`, and the `main_refines_spec` theorem an `@refines(…)`
annotation emits.

**Status: PARTIALLY FIXED 2026-10-19 (`work/formal637-docs`). FIVE more rows
are registered, so SEVEN of the eleven annotated examples now carry an
all-inputs theorem rather than the finite range: `Specs.consecutiveProduct64`,
`Specs.succSquare64`, `Specs.doubleSuccOne64`, `Specs.maskedMix64` and
`Specs.isNonzero64`, beside the existing `Specs.id64` and
`Specs.factorial64`.  They are a new `"closed"` row kind — a straight-line
model is one closed word expression, so the theorem is not an induction: the
row states the model body it was written for (compared exactly, like the
recursive shape) and the tactic block that closes THAT body.  All five clauses
are checked end to end by `test_formal_specs.py`'s
`the_straight_line_all_inputs_theorems_typecheck`, which reads each model back
out of the generated proof and asks Lean about the clause in isolation.  §"The
straight-line rows, 2026-10-19" has the measurements.  The remaining three are
`Specs.abs64` (true for all inputs, but the proof needs signed `asInt`
reasoning that is not a two-line tactic) and `Specs.stepConst64` /
`Specs.shiftMix64`, whose all-inputs statements are FALSE outside the finite
range for a reason that is the specification's own domain (below), so they need
a stated hypothesis rather than a row.  Everything below this paragraph is the
2026-10-14 record and is unchanged.**

**Status: PARTIALLY FIXED 2026-10-14 (`work/formal418-docs`). The all-inputs
claim is now EMITTED for the specifications whose model shape has a row, the
missing `UInt64` multiplication lemma is landed and proved, and the boundary is
a tested rule rather than a sentence — but only TWO rows exist (`Specs.id64`,
`Specs.factorial64`) of the eleven annotated examples, and the "must be a
`lib/ProofLib.lean` theorem" half of the 2026-10-05 diagnosis below is WRONG in a
second way that only shows up on a MERGED tree. §"What landed 2026-10-14" is the
measurement; everything under it is the 2026-10-05 record and is unchanged except
where that section says so.** Found 2026-10-05 while landing
`work/formal36-spec-refinement`.

**`u64_ofNat_mul` now exists TWICE, and that is a merge artefact rather than a
decision.** Two workers landed the same three-line lemma independently:

  * `work/formal405-docs` put it in `lib/ProofLib.lean` (master, commit 3941dade
    re-pinned `test_formal_admitted.py::AXIOM_CLOSURE`'s `ProofLib` row to
    `(315, 62, 248, 0, 5, 0)` for it); and
  * `work/formal418-docs` put a copy in `lib/Specs.lean`, with a documented
    reason — `ProofLib.lean`'s 27 MB `.olean` is past the 8 GB a bounded change
    may spend, and a generated all-inputs induction is emitted into a file that
    already imports `Specs`, so the name is in scope where it is used.

Both were in this tree, with the same statement and a core-lemma-only proof
(`rw [...]` in ProofLib, `simp [...]` in Specs).

**RESOLVED 2026-10-18 (`work/bunny-merge26-r2-r2`).** `Specs.u64_ofNat_mul` is
deleted and `formal/specs.py::ALL_INPUTS`'s `lemma=` names the BARE
`u64_ofNat_mul` — bare, because `lib/ProofLib.lean` has **no `ProofLib`
namespace**: its declarations sit at the root, so `ProofLib.u64_ofNat_mul` is an
unknown identifier (measured with `lean`, on a file that imports ProofLib, work,
Refine and Specs and does `open Specs`). The collapse's proposed next step said
"name `ProofLib.u64_ofNat_mul`", and that half was wrong; the bare name is what
every other library fact already uses in generated text (`arm64_reg`,
`mem_read_u64`, …).

The memory objection does not survive contact with the tree: `lib/Specs.lean`
rebuilds in **1.1 s / 0.2 GB** (measured through `formal/lean.py::ensure_library`
under an 8 GB reservation), because the shim was never what made it cheap —
`ProofLib.lean` is what is past the ceiling, and `Specs.lean` does not need
rebuilding when it does not change. The doc said this was the one verification a
light worker could not afford; it is affordable, and the `BREACH` it recorded was
from running the whole of `test_formal_specs.py` rather than the rows that
cover this change.

Verified here: the six relevant `test_formal_specs.py` rows PASS, including
`test_the_recursive_all_inputs_theorem_typechecks`, which lays the emitted
all-inputs clause beside the model read back out of a generated proof and asks
`lean` about it — the end-to-end check that the bare name resolves, and it does
not resolve before the `Specs.lean` edit. `AXIOM_CLOSURE`'s `Specs` row
measures (66, 0, 66, 0, 0, 0) after the deletion, partition closed.

## What landed 2026-10-14, and the two things the 2026-10-05 diagnosis got wrong

`refines_section` now emits a third theorem beside the two it emitted before,
`main_refines_all_inputs`, whenever the annotated specification has a row in
`formal/specs.py::ALL_INPUTS` **and** the program's emitted model has the shape
that row names. The theorem is the doc's own shape, over the whole word:

```lean
theorem main_refines_all_inputs (w : UInt64)
    (hfits : Specs.factorial w.toNat < 2 ^ 64) :
    mojo w = Specs.factorial64 w := by …
```

**Wrong #1: the multiplication lemma is NOT "a DIFFERENT proof".** The
2026-10-05 section below says `u64_ofNat_mul` "is a DIFFERENT proof, not another
`Nat` rewrite", and that is false. It is the SAME `UInt64.toNat.inj` reduction
the two existing facts use, in three lines, core-lemmas only:

```lean
theorem u64_ofNat_mul (a b : Nat) :
    UInt64.ofNat a * UInt64.ofNat b = UInt64.ofNat (a * b) := by
  apply UInt64.toNat.inj
  simp [UInt64.toNat_mul, UInt64.toNat_ofNat', Nat.mul_mod]
```

so the reason the generator half "cannot land ahead of it" was a missing lemma,
not a missing proof technique. It is landed — **in `lib/Specs.lean`, because
`work/formal405-docs` had already landed it in `lib/ProofLib.lean` and a
`ProofLib.lean` edit rebuilds that module's 27 MB `.olean`, which measured under
`tools/memslot.py --gb 8` BREACHES the 8 GB ceiling** (`memcap: BREACH 8.0
GB > 8.0 GB ceiling (100%)`, 1m54s, 2026-10-14; the same measurement
`bugs/formal/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` records at 9.8 GB).
`Specs.lean` rebuilds in ~2 s / 0.2 GB, it is the module an annotated program
already imports, and the proof is core-lemma-only. **On this merged tree the
"because" no longer holds** — `lib/ProofLib.lean` already states the lemma, so
the two copies were one theorem stated twice, and they have been collapsed (the
RESOLVED block at the top of this document says which copy went and what the
emitter cites now).

**What the emitter covers, and the boundary is a rule with a test.** A row names
the `Nat` function a `…64` word reading truncates, its step equation, the word
fact the step rewrites through, and the model SHAPE the induction is written
for. The emitter writes the theorem only when the model text it is handed has
that shape (`formal/specs.py::_recursive_shape` / `_identity_shape`), so a
registered specification on a differently-shaped model gets the finite-range
theorem it always had and no false all-inputs claim. `ALL_INPUTS` has two rows:

| spec | model shape | status |
|---|---|---|
| `Specs.id64` | `UInt64 → UInt64`, the identity | emitted, and checked end to end (`test_formal_specs.py`, both backends, `PASS=10 FAIL=0`) |
| `Specs.factorial64` | `Nat → UInt64`, `(ofNat (k+1)) * go k` | emitted; the CLAUSE is checked by an isolated `run_lean`, because `fact`'s own proof file is `lean-rejected` on master for an unrelated reason |

**Why the factorial row's check is not the whole file.** `fact` is
`lean-rejected` in `tools/formal_proof_census_baseline.json` \u2014 a row that was
stale and has since been re-pinned on master (3941dade), so the doc that recorded
the staleness is deleted \u2014 so asking
Lean about `fact_proof.lean` reports THAT and not this layer. So
`test_formal_specs.py::test_the_recursive_all_inputs_theorem_typechecks` reads
the model back out of the generated file, lays the emitter's clause beside it
with the same imports, and asks Lean about that — the narrowest thing that shows
the emitted clause is a proof rather than text.

**What is still open, and it is what it always was: rows.** Nine of the eleven
annotated examples are unregistered, so they still claim only the range. The
straight-line shapes (`abs64`, `consecutiveProduct64`, `succSquare64`,
`doubleSuccOne64`, `maskedMix64`, `shiftMix64`, `stepConst64`, `isNonzero64`)
each need their own induction or `toNat`/`ofNat` bridge, and the earlier "eleven
model shapes" estimate is roughly right for those. A row is cheap and bounded
(one `AllInputs`, one shape recogniser arm if the shape is new, one Lean clause
checked in isolation), so this is a queue of small pieces rather than a project
— which is the one thing the 2026-10-05 Status, framing the whole thing as
un-landable, obscured.


## The straight-line rows, 2026-10-19

**Five more specifications now claim the whole word.** `ALL_INPUTS` grew a
`"closed"` kind: a straight-line program's model is ONE closed `UInt64`
expression, so its all-inputs theorem is not an induction — unfold both sides
and the goal is a word identity. A row carries the model BODY it was written
for and the tactic block that closes that body, because the two are one claim;
`_closed_shape` compares the body exactly (the same refusal rule
`_recursive_shape` follows) and the emitter returns "" rather than a theorem
above a model it does not recognise.

| spec | model body | what closes it |
|---|---|---|
| `Specs.consecutiveProduct64` | `((n * n) + n)` | `simp [...]`, then `rw [UInt64.mul_add, UInt64.mul_one]` |
| `Specs.succSquare64` | `((n + 1) * (n + 1))` | `simp [...]` |
| `Specs.doubleSuccOne64` | `((n * 2) + 1)` | `simp [...]`, then `rw [UInt64.mul_comm w 2]` |
| `Specs.maskedMix64` | `(((n &&& 255) + (n ||| 240)) + (n ^^^ 85))` | `simp [...]` |
| `Specs.isNonzero64` | `(if n ≠ 0 then 1 else 0)` | split on `w.toNat = 0`, bridge with `UInt64.toNat_inj`, `simp [...]` |

**`bv_decide` is not the tool, and that is measured rather than assumed.**
`w * w + w = w * (w + 1)` is a bitvector identity, but `bv_decide` times out on
it (the SAT solver does not get associativity/commutativity for free, and the
`acNf` option is not on by default); the two rewrites above close it in one
step. So the proof is per row rather than one generic tactic, which is what the
`proof` field is.

**What each clause is checked against.** `test_formal_specs.py`'s
`the_straight_line_all_inputs_theorems_typecheck` builds each annotated example
(`check=False`), reads the `_go` and `mojo` definitions back out of the
generated proof, lays the emitted clause beside those exact definitions with
the same imports, and runs Lean on that file. That is the same narrow shape the
recursive row's test uses, and for the same reason: the enclosing proof file's
end-to-end section is red for unrelated reasons on some examples, so asking
about the whole file would report that instead of this layer. The whole file
reports `PASS=12 FAIL=0`, and the five clauses elaborate with `rc=0`.

**The three that are still not rows, and the two different reasons:**

* `Specs.abs64` is TRUE for every word, but its proof is not a two-line tactic:
  the model branches on the SIGNED order (`n ^^^ 2^63 > 0 ^^^ 2^63`, which is
  `n > 0` signed) while the specification reads `asInt w` and `absInt`. The
  goal after `simp` still carries both the sign-bit split and the
  `wordLimit`/`toNat` conversion, so it is a real proof, not a missing row.
* `Specs.stepConst64` and `Specs.shiftMix64` are FALSE outside the finite
  range, and this is a property of the SPECIFICATION's domain rather than of
  the program. `bigconst` branches on the SIGNED comparison `n <= 0`, so a word
  whose top bit is set returns 0, while `stepConst w.toNat` returns
  `100000 + w.toNat` (a huge natural). `shiftlr` computes an ARITHMETIC right
  shift (`asr64`), while `Nat.shiftRight` is LOGICAL, so the two disagree for
  every negative word. An all-inputs row for either would be a false theorem;
  what they need is a stated no-wrap/no-negative hypothesis (the shape the
  recursive row already has in `hfits`), not a `closed` row.

## What is landed, in one paragraph

`lib/Specs.lean` is a hand-written specification layer — `fib`, `gcd`,
`factorial`, `sumTo`, `absInt`, binary search, `isPrime`, `collatzStep`,
`asciiLength`, `popcount` and the word readings that put them at the machine's
argument domain. A program asks to be checked against one with
`@refines(Specs.fib64; 64)`, and its generated proof then carries

    theorem main_model_refines_spec :
      ∀ n ∈ List.range 64, mojo (UInt64.ofNat n) = Specs.fib64 (UInt64.ofNat n)

closed by `native_decide`, and (arm64 only) `main_refines_spec`, which composes
it with the universal theorem. Nine examples carry the annotation and all nine
check.

## The gap

**The claim is over a finite range and not over all inputs.**  `spec_refinement`
requires the range, `MAX_RANGE` caps it at 1024, and `formal/specs.py`'s emitted
docstring says so in the file itself. The reasons are two, and they are
different:

1. **The instrument is finite.** `∀ n ∈ List.range N, mojo (UInt64.ofNat n) =
   Specs.fib64 (UInt64.ofNat n)` has a `Decidable` instance, so `native_decide`
   evaluates it; `∀ n, mojo (UInt64.ofNat n) = Specs.fib64 (UInt64.ofNat n)`
   does not, and proving it is a different proof per example. There is no
   `Finset` in this toolchain's import closure (`lib/ProofLib.lean` imports
   `Lean` alone), so the finite range this can be written in is `List.range N`
   rather than something with a nicer membership.

2. **The claim is FALSE outside the range, and that is not an accident.**  A
   word reading is `UInt64.ofNat` of a mathematical value, so
   `mojo n = Specs.fib64 n` is false for every `n` whose Fibonacci number does
   not fit in a word — the model's `n` is a word and the specification's is a
   `Nat`, and the two only agree while no truncation happens. So even a perfect
   all-inputs proof would have to be stated over the no-wrap region, which is a
   statement about where the specification fits, not about the program alone.
   `lib/Specs.lean` has `fitsWord`, `wordLimit`, `wordMax` and
   `small_lt_wordLimit` for that region; what it does not have is a per-example
   theorem that the model agrees with the specification *throughout* it.

## Why it is worth closing, and what closing it looks like

The all-inputs claim is the one a reader of `formal/examples/fib.mojo` actually
wants: "the machine computes Fibonacci" rather than "the machine computes
Fibonacci for 0 ≤ n < 64". It is also the claim that would catch a model bug at
an input nobody thought to enumerate, which is the whole class of defect a
self-consistency theorem cannot see.

It is per example, and the shape of the proof is visible in what is already
emitted. For a recursion whose model is a structural `Nat` function — `fact`,
`sum`, `sqsum`, `fib` — the generated file already carries

    def fact_go : Nat → UInt64
      | 0 => (UInt64.ofNat 1)
      | k + 1 => ((UInt64.ofNat (k + 1)) * fact_go k)

    theorem fact_go_succ (k : Nat) : fact_go (k + 1) = (k + 1) * fact_go k := rfl

so the missing half is a strong induction on `Nat` whose step rewrites
`fact_go_succ` and the specification's own equation, and whose arithmetic goal
is a `UInt64` multiplication that does not wrap — which needs a
`u64_ofNat_mul` lemma (there is `u64_ofNat_add` and `u64_ofNat_sub` in
`lib/ProofLib.lean` at lines 741 and 748, and no multiplication analogue) and a
no-wrap bound discharged from the range hypothesis. The emitter knows the shape
of the `_go` it wrote, so it can emit the induction; what it cannot do is
invent the specification's equations, which is why the lemma belongs in
`lib/Specs.lean` next to the specification and the induction next to the model.

The generator half is `formal/arm64_proof_gen.py::_gen_universal_e2e_cfg`'s
neighbour: a `_gen_all_inputs_refinement(func_name, spec)` that emits

    theorem main_refines_all_inputs (n : Nat) (hfits : Specs.fib n < 2^64) :
      mojo (UInt64.ofNat n) = Specs.fib64 (UInt64.ofNat n)

by induction on the model's own recursion. It is deliberately NOT attempted
here, because an induction that has to be right for eleven different model
shapes is exactly the kind of thing that should land with its own negative
control (a deliberately wrong specification must make the induction fail, not
merely the finite check).

## Re-measured 2026-10-05: the limit is where it was, and the ONE missing
##      library fact is named exactly

This round was given the doc and could not close it — the generator half is a
per-example induction and the library half is a `lib/ProofLib.lean` theorem, and
the brief allows no Lean run beyond the one test covering a change. **So this
section is a measurement, not a fix**, and what it adds over the original is a
sharpened statement of the blocker.

**The gap is not "the range is finite".** It is that the ALL-INPUTS statement
needs a `UInt64` MULTIPLICATION lemma and there is no multiplication analogue of
the two that exist:

```
$ grep -n 'u64_ofNat_add\|u64_ofNat_sub\|u64_ofNat_mul' lib/ProofLib.lean
741:theorem u64_ofNat_add (a b : Nat) : UInt64.ofNat a + UInt64.ofNat b = ...
748:theorem u64_ofNat_sub (a b : Nat) (h : b ≤ a) (hM : a < 2^64) : ...
(no `u64_ofNat_mul`)
```

**CORRECTED 2026-10-13**: `u64_ofNat_mul` is now at `lib/ProofLib.lean:770`, so
the line above is the 2026-10-05 measurement and not the current state.

That is the whole of why a `fact`-shaped induction cannot be written today: its
arithmetic goal is `UInt64.ofNat (k+1) * fact_go k` against a specification in
`Nat`, and — as `u64_ofNat_add` shows — the way this library discharges that
class of goal is `apply UInt64.toNat.inj` and reduce to a `Nat` statement about
`% 2^64`. **A multiplication lemma is a DIFFERENT proof, not another `Nat`
rewrite**, because the residue of a product is not the product of the residues.
That is the concrete thing to establish first, and it is why the generator half
cannot land ahead of it the way the range-loop fix's refusal could.

**`lib/Specs.lean` already has the no-wrap region** — `fitsWord`, `wordLimit`,
`wordMax`, `small_lt_wordLimit`, `ofNat_toNat` (`lib/Specs.lean:59-101`) — so the
*statement* an all-inputs theorem needs is expressible; what is missing is the
per-example induction and, under it, the multiplication fact. The doc's §"Why it
is worth closing" is therefore accurate as written and the region is not the
missing piece.

**The layer itself is unchanged and green**: `python3 test_formal_specs.py` is
8/8, including the negative control (`a wrong specification is rejected`), so
the finite-range claim is still EVALUATED rather than believed — which is the
property that makes the missing induction a coverage gap rather than a soundness
one.

**The x86-64 half is as described**: `refines_section(..., machine_half=False)`
emits the model half only, and `test_formal_specs.py`'s
`the_x86_64_backend_gets_the_model_half_only` pins it.

## What is NOT the problem

**This is not a hole in the emitted theorems.** Both are closed; the census
reports `n_admitted 0` and `n_sorries 0` for every annotated example
(`tools/formal_proof_census_baseline.json`, the eleven rows measured
2026-10-05). The limit is what they SAY, and it is stated in the file each time
they are emitted.

**This is also not the x86-64 half.** That backend emits only
`main_model_refines_spec` and says why — its end-to-end theorem is a `sorry`, so
composing with it would give Lean a statement about the machine it accepts while
resting on a hole. `test_formal_specs.py::test_the_x86_64_backend_gets_the_model_half_only`
is that claim.

## How to see the current state

    python3 test_formal_specs.py            # 8 cases, including the negative control
    grep -c '^theorem main_refines_spec' output/<stem>_proof.lean

`main_refines_spec` present and `List.range N` in its statement is the layer
working as landed. What is missing is `main_refines_all_inputs`.