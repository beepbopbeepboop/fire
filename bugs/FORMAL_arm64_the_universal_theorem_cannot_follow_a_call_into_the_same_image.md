# FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image: 20 of 78 functions, the largest cause in the proof-breadth census

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