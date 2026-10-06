# FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image: 20 of 78 functions, the largest cause in the proof-breadth census

**Status 2026-10-05 (`work/formal40-4-r2`): the ONE-CALL-SITE case is FIXED and
proved, and the reduce is the whole limit — but the CENSUS was not re-run, so
"20 of 78" is still the last measurement of how much this is worth.** Steps 1
and 2 of "The exact next step" below landed; step 3 (recursion) did not, and
neither did the two-call-site case. Everything above this paragraph is the
record of how the question got here.

**What landed, in three pieces and no library change.**

* `_same_image_call_plan(code, base, func_entry, func_end)` decides the one
  shape a return address is a **constant** for, and returns `(None, why)` for
  every other. It is read twice — by the refusal a reader sees and by the walk —
  so the two cannot disagree about which programs are followable.
* `ctx["ret_to"]` carries that constant down the descent. A `RET` reached with
  it set states `x30 = ret_to` instead of `x30 = exit_pc`, emits
  `hpc_r_N : (s_N).pc = ret_to` off the same fact, and **continues** at the
  caller's own next block; the caller's continuation drops it, so the caller's
  own `RET` still returns to the halt address.
* the `bl` arm descends into the callee instead of refusing, and `_opaque`
  became the first call **out of the image** rather than the first call at all —
  which is what lets `exit_at`, the reachability theorem and the suppressed
  concrete run test keep meaning "a call the model cannot execute". A followed
  same-image call therefore gets the FULL theorem (`s.x0 = mojo n`, plus the
  concrete run test), not the reachability one.

**The reduce is smaller than step 1 feared, because two of the three things it
says has to be checked were already true.** `_cfg_blocks` spans every function
from the entry to the image's last `RET`, so **the callee's blocks are already
among the walk's blocks** — following the call is one edge into an existing
block plus one constant, not a second walk. And `RET`'s effect on `pc` is
already `x30.toNat`, so the fact a callee's return needs is a rewrite of the
`hx30_*` the walk already emits. Nothing in `lib/ProofLib.lean` changed, which
is why this was landable by a worker who may not run the Lean gate: the
`lib/*.olean`s come from the CAS and a generated proof checks in 3.8 GB.

Step 1's open question — "whether `FrameOk`'s 15 conjuncts survive `x30` being
a hypothesis rather than a loaded word" — turned out not to arise: `x30` is
never a hypothesis. It is a **constant the emitter writes into the record
update** the `BL` step already performs, and the callee's prologue/epilogue pair
carries it through the frame the same way every other value is carried.

**Measured, arm64, through `formal/lean.py::run_lean`:**

| program | before | after |
|---|---|---|
| `helper(n) = n * 2`, `main(x) = helper(x)` | REFUSED by name | **rc=0, 5051 lines, 0 sorries, 3.8 GB, ~4 min** |
| the doc's own reproducer, with a conditional `helper` | REFUSED by name | generates; the certificate exceeds Lean's own `-M 6144` at 6.5 GB |

**And the second row is not this doc's bill.** A program with **no call at all**
and the same number of conditionals (three `if`s: 7045-line proof, 7.3 GB)
exceeds the same limit. The boundary is the walk's **path count**, which follows
the callee's conditionals because the walk explores both edges of every
conditional it meets — and that is
`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`'s, not this
row's. That measurement is what lets this land without waiting on it.

**Behaviour-preserving for everything that already built**, measured rather than
argued: all **52 `formal/examples/*.mojo` × 2 backends = 104 proofs** are
byte-identical (sha256 of the emitted `.lean`) against `HEAD`'s generator.

**Both architectures.** x86-64 was never refusing this: `formal/x86_64_proof_gen.py`
emits a proof for the same program today (`test_formal_call_proof_gen.py`'s
`test_x86_64_omits_the_bridge_and_says_why` has asserted it all along), so this
row's subject was the arm64 walk only and the fix is arm64-only by that fact.
The doc's "both architectures" claim in the header is about the census, where
x86-64's row is measured separately.

**What is left, and it is step 2 and step 3.**

1. **Two call sites.** `REFUSED['callee_chain']` (`main → b → c`) still refuses,
   naming the reason: `x30` at the callee's `RET` is then a property of the CALL
   PATH. A return-address map keyed by `(return_pc)` would do it, and the walk
   already has the per-path `ctx` to carry it — but two call sites into the same
   image means the callee's blocks are entered twice per path, so the block
   certificates and the `hprior` memo have to be told the difference. That is a
   real measurement to make before writing it: **how many of the census's 78 are
   two-call-site rather than one** is not known, and it decides whether this is a
   day's work or a week.
2. **Recursion** is unchanged and is step 3: `bugs/FORMAL_ast_bridge_carries_one_
   argument_per_call.md`'s arm64 half, which this doc's own text says is the same
   limit. The plan now SAYS so — a callee that calls at all is refused with
   "following it is RECURSION and not a return-address map" — where before it
   fell into the recursion arm and reported a program with no recursion as a
   recursion problem.
3. **The census was not re-run.** `tools/formal_proof_breadth.py --no-check` is
   cheap (156 verdicts in 2 s, 0.1 GB) but it is a `formal_sweep`-class run and
   this worker was told not to; whoever gates this should re-run the doc's own
   command to turn "20 of 78" into a measured after. It is the one number here
   that is a fact about the tree before the change and not about it after.

**Area:** FORMAL (the proof layer's machine model, arm64) · **found by**
`tools/formal_proof_breadth.py`'s second round, phase A · **both
architectures** (x86-64 emits a proof for the same programs; §0.6.3's table) ·
**filed 2026-10-04, NOT fixed, and not fixable by a worker who may not run
Lean** — the oracle for a machine-model change is the proof it produces, so this
needs the formal suite behind it rather than one example.


## What I ran

    python3 tools/memslot.py --gb 8 --label proofbreadth2 -- \
      python3 -u tools/formal_proof_breadth.py --no-check --arch both -j 4 -t 400 \
        --repo 60 --examples 45 --example-offset 1 --admit-returns \
        --exclude-seen bugs/sweeps/proof_breadth_2026-10-03.jsonl \
        --ledger bugs/sweeps/proof_breadth_2026-10-04_round2-phaseA.jsonl
    # 156/156 verdicts in 2s; peak 0.1 GB

and the refusal itself, whole, on the minimal program below.

## What I saw

    build: universal theorem: the call at 0x100000308 targets 0x10000031c, a
    second function in the same image.  The machine model follows it -- every
    byte is present, and the callee's `ret` returns through `x30` -- but the CFG
    walk is per-function, and following the call means entering the callee's
    blocks and then dispatching on `x30`, whose value is a property of the call
    path rather than of the block.  That is interprocedural walking: a
    return-address map in the framework, not a missing case here.  The semantic
    model for the call is correct and emitted (see the `_go` definitions above);
    what is missing is the machine half.

from

    def helper(n):
        if n > 3:
            return n * 2
        return n + 1

    def main(x):
        return helper(x)

on arm64. **20 of the census's 78 items stop here**, and it is the largest
single family by a factor of two and a half — §0.6.3's table is the `Counter`,
and the families either side of it are 16 (a string value) and 7 (a field
access through a value).

## What I expected

A program whose entry calls one other function in the same image to get a proof.
Every byte of it is in the image; `arm64_proof_gen.py` already emits the semantic
model for the callee (the refusal says so in its own last sentence: "the `_go`
definitions above"), so the only missing half is the machine one.

## The exact next step

**A return-address map, and the reduce is below.** The walk already knows the one
thing that makes it hard: `x30` at the callee's `RET` is a property of the CALL
PATH, not of the block. With a single call site on a path, `x30` is a constant
for that path and the walk can carry it as an assumption — the same shape as the
window-peel chain `FrameOk`'s memory clause uses, which is why
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` is the closest thing in
the tree to the work.

1. **Prove the reduce is the whole limit.** The minimal case above is one call
   site, one return, no recursion, and it is refused. A walk that (a) records
   `{call_pc: return_pc}` as it descends, (b) enters the callee's blocks with
   `x30 := return_pc` as a hypothesis, and (c) at `RET` dispatches on the current
   hypothesis rather than on the block, should discharge it. What has to be
   checked before writing it: whether `FrameOk`'s 15 conjuncts survive `x30`
   being a hypothesis rather than a loaded word (`all_goals intro j hj` will not
   do it — §6's first bullet records 14 of the 15 having no binders for it).
2. **Then the one-call-site case, then two.** `_unfollowable_calls` already
   returns the LIST and the caller already refuses when there is more than one
   ("ONE halt address cannot discharge them"), so the second call site is a
   separate step rather than a new mechanism: a return-address map keyed by
   `(return_pc)` with the caller's own `x30` saved across the call.
3. **Recursion last**, and it is the same limit as
   `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`'s arm64 half — that
   doc says so in its own words ("On arm64 the same program is REFUSED, by a
   different and larger gap: the CFG walk is per-function … neither is this
   doc's"), which is why this is a separate file rather than an edit to it.

## Why it is worth doing before anything else in this census

§0.6.3's arithmetic: **59 % of a 78-function corpus of this repository's own
source reaches the proof layer, and the largest single reason it does not is this
one.** The two families either side of it (16 string-valued constructs, 7 field
accesses) are value-model work with their own docs and their own claims; this is
a single missing mechanism, and it is the only row in the census that is one
function long in the right direction.