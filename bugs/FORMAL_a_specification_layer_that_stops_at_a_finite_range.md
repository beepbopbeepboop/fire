# the specification layer states a refinement over a FINITE range, and the all-inputs claim is not attempted

**Area:** FORMAL, both backends — `formal/specs.py`, `lib/Specs.lean`, and the
`main_refines_spec` theorem an `@refines(…)` annotation emits. **Status: open,
re-measured 2026-10-05, and deliberately so; this is the limit of the layer as
landed, not a defect in it.** Found 2026-10-05 while landing
`work/formal36-spec-refinement`. §"Re-measured" names the single library fact the
all-inputs statement is waiting on.

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