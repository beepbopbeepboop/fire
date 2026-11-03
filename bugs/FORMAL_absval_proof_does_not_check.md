# `formal/examples/absval.mojo`'s arm64 proof no longer checks — a frame-slot peel's address does not match the goal

## Status

**OPEN, MEASURED 2026-10-12 (`work/formal303-docs`).** `absval` is NOT in
`test_formal.py`'s `EXPECTED_FAILURES`, and it used to pass: the 2026-10-04
sweeps under `bugs/sweeps/proof_breadth_2026-10-04*.jsonl` record
`examples/absval.mojo` / `arm64` as `cls: "pass"`, `n_sorries: 0`, `5660`
proof lines, and `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`
line 117 states "proof emitted and **accepted by Lean** (3.1 GB peak, exit 0)".
On this tree the proof is emitted and Lean REJECTS it. The `formal` gate row
that would have caught it is disabled (the task's environment), so nothing in
the gate sees it.

Found while running the corpus for the `maxRecDepth` fix in
`bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`
(`python3 test_formal.py --backend arm64 -j 2 ...`: `absval` reported `FAIL`).

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import os,sys; sys.path.insert(0,os.getcwd())
from formal.lean import check_proof_cached
r = check_proof_cached('.tmp/absval_proof.lean', repo_root=os.getcwd())
print(r[0], r[3]); print(r[1][:600])"
```

(the proof is produced by `python3 test_formal.py --backend arm64 absval`, or by
`fb.compile_formal('formal/examples/absval.mojo', arch='arm64', prove=True,
check=False)`; the file is 4642 lines today).

## What I saw

```
OK False sorries 0
absval_proof.lean:4345:10: error: Tactic `rewrite` failed: Did not find an occurrence of the pattern
  mem_read_u64
    (mem_write_u64 (mem_write_u64 ?m.975 (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16).toNat ?m.988)
      (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16 + 8).toNat ?m.989)
    (s_0.sp - UInt64.ofNat 32 - UInt64.ofNat 16).toNat
in the target expression
  arm64_matches_condition 13
        (arm64_subs_flags
          (mem_read_u64
            (mem_write_u64
              (mem_write_u64 s_0.mem (s_0.sp - UInt64.ofNat 131072 - UInt64.ofNat 16).toNat (n + UInt64.ofNat 0))
              ( ...
```

The peel lemma's pattern names a slot at `s_0.sp - 32 - 16`; the goal's store
chain is at `s_0.sp - 131072 - 16`. The addresses differ by the emitter's
128 KiB frame stride (`_SCRATCH`), so this is the same class as
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` and
`bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`:
the frame/window canonicalisation emits a peel whose `K` does not match the
address the goal actually carries.

It is NOT the `maxRecDepth` regression fixed on the same tree: `absval` fails
with this `rewrite` error both at the old emitted `maxRecDepth 100000` and at
the new `1000000`, so the constant is not the cause.

## What I expected

Lean accepts the proof, as `FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`
and the 2026-10-04 sweep ledger say it did. `absval` is not declared a gap in
`test_formal.py`'s `EXPECTED_FAILURES`, so a run reports it as an unexpected
`FAIL`.

## The exact next step

1. Reproduce cheaply, no gate:
   `python3 test_formal.py --backend arm64 absval` under
   `python3 tools/memslot.py --gb 8 --label t --`.
2. Find the emission site that produced the mismatching `rw [mem_read_write...
   (K := 32) ...]` at `absval_proof.lean:4345` (`formal/arm64_proof_gen.py`'s
   FrameOk-window peel, `_emit_peels`/`mem_read_write_below`/`_pair_below`) and
   reconcile the `K` list it writes against the store stack the goal unfolds to
   — the goal carries `- 131072 - 16`, the pattern carries `- 32 - 16`.
3. Whoever can run the corpus should re-run
   `test_formal.py --backend arm64` (all stems): `absval` is one unexpected red,
   and the same frame-machinery change may have moved others (a first
   `-j 2` pass over the 31 declared gaps showed only `main_calls_helper`
   flipping to PASS, so the unexpected reds are the ones to enumerate).

## Why it is worth a doc rather than a silent skip

A formerly-passing example that now fails is a regression, and the gate row
that runs the corpus is disabled in this environment — so without a doc the
only record is a sweep ledger from 2026-10-04 that says the opposite.
