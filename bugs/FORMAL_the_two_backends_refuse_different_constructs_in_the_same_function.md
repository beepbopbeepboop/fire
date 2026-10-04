# FORMAL_the_two_backends_refuse_different_constructs_in_the_same_function: a class that agrees hides a subject that does not

**Area:** FORMAL (both emitters) · **found by** the proof-breadth census's
cross-architecture column, which is the only instrument here that compares the
two machines on the *same* function · **filed 2026-10-04, NOT fixed** — one half
of it is a capability gap that needs a `ProofLib.lean` arm, the other half is a
measurement nobody has made.

## What I ran

    python3 tools/memslot.py --gb 8 --label proofbreadth2 -- \
      python3 -u tools/formal_proof_breadth.py --no-check --arch both -j 4 -t 400 \
        --repo 60 --examples 45 --example-offset 1 --admit-returns \
        --exclude-seen bugs/sweeps/proof_breadth_2026-10-03.jsonl \
        --ledger bugs/sweeps/proof_breadth_2026-10-04_round2-phaseA.jsonl

then, over that ledger, a diff of each item's two `detail` fields.

## What I saw

**The census reports one class per item per architecture, and a class is not a
subject.** 32 of round 2's 78 items are `codegen-refused` on both machines, and
three of them were refused for DIFFERENT CONSTRUCTS:

| item | arm64 | x86-64 |
|---|---|---|
| `test_formal_math.py:303:isqrt_source` | *"'MAX64' has no home: this module declares no module-level name by that spelling"* — a module constant | *"'%' is refused when the left operand is a string"* — a string operator |
| `mojo/backend_gimple/emit_infra.py:2983:_new_jbp_temp` | *"'gen.temp_counter' is a field access through 'gen'"* | *"augmented assignment target must be a plain name on the formal x86-64 path (got MemberExpr)"* |
| `test_formal_stat.py:179:corpus` | `…131072 left for containers` | `…16384 left for containers` |

The third is honest — the two frames really are that different — and the first
is now gone: `formal/model.py`'s module-level folder answers `MAX64 = 2 ** 63 - 1`
(`commit e2740609`), so both machines refuse that function on the string and the
census's two columns are about the same thing again. **2 of 32 differ now.**

**The second is not fixed and is a genuine capability divergence.**
`formal/x86_64_codegen.py:2465` accepts an augmented-assignment target only when
it is a plain name or a member that is one of THIS frame's slots; anything else
is refused by name. `formal/arm64_codegen.py:2180` accepts any member for which
`_member_slot_key` answers, with no frame-slot condition. So for a member
through a receiver the function does not own — `gen.temp_counter`, which is what
this repository's own `emit_infra.py` writes — **arm64 lowers it and x86-64
refuses it.**

## What I expected

Either the same refusal from both machines, or one of them to be wrong.

## The exact next step

1. **Measure arm64's wider acceptance before deciding which side is right.** The
   question is whether `x.y += 1` through a non-frame receiver computes the
   address the source means on arm64. This doc does not claim it does not: the
   shape needs a receiver this path can only get from a struct field or a
   returned frame, and the two minimal programs I built
   (`p.c += 3` on a local struct — both build, both print 17, correct; and
   `q.p.c += 5` through a nested frame — both refuse at the `print`, for a
   different and honest reason) stop short of it. `tools/formal_fuzz.py --mix
   limits` is the instrument for finding the shape; `test_formal_run.py`'s
   `both_arch_*` rows are where the answer belongs.
2. **If arm64 is right, x86-64's frame-slot condition is a missing arm** and the
   refusal is wrong for this repository's own source. If arm64 is wrong, it is a
   silent miscompile on one architecture — which is the failure mode
   `formal/model.py`'s whole design exists to prevent, and the reason this is
   filed rather than closed as "x86-64 is stricter".
3. **Nothing in the census should be read as settled while a class can hide a
   subject.** The cheap improvement is to make the tool's per-item report print
   both `detail`s when they differ, which is a line in `report()` and no
   behaviour change — §0.6.4's before/after (3 → 2 differing items) is the
   measurement that says the cross-architecture column is worth having at all.