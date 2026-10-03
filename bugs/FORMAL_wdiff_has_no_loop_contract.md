# `formal/examples/wdiff.mojo` has no loop contract on arm64, so the arm64 formal corpus job is red

**Area:** FORMAL (the arm64 proof generator's loop-contract arm). **Status: OPEN,
measured, not fixed.** Found 2026-10-03 while landing the entry-arity work on
`work/formal16-3`; it is not that branch's regression and is not in its claims.

## What I ran

`wdiff` is the one dec1-family example the x30 filing names as still typechecking
("the one that typechecks (`wdiff`) has no call in it"), and
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` treats it as the control.
It is not typechecking:

```
$ python3 test_formal.py -j 1 wdiff
[1/1] FAIL  wdiff  (build/proof failed: .../formal/arm64_proof_gen.py", line 5433,
        in emit_block
    raise ValueError(
        f"unsupported edge to {hex(tgt)} (loop back-edge / continuation; "
        "no loop contract matches)")
ValueError: unsupported edge to 0x1000002fc (loop back-edge / continuation; no
loop contract matches))
```

Reproduced on **`master`**, not only on the branch: a copy of `master` at
`99cdb9b7` with the *only* change being the `audit_step_table` comment fix (see
below) fails identically. The offending edge is the `while n != 0:` back edge,
and the raise is the `else` of the loop-contract dispatch in
`formal/arm64_proof_gen.py`'s `_gen_universal_e2e_cfg` `b`-block arm.

## Why it matters more than one example

`tools/suite.py` registers

```
test('formal', [PY, 'test_formal.py'], j=True, deps=['preflight', 'prooflib'],
     desc='every formal/examples/*.mojo typechecks its generated Lean proof')
```

with **no `expect=` and no `disabled=`** — so `wdiff` is an UNEXPECTED failure
of a job the registry says must be green, and it is not in
`test_formal.py`'s `EXPECTED_FAILURES` (which holds `fib`, `countdown`, `wge`,
`subscript_var`).

Two other things were red in the same job on `master`, and both are recorded
elsewhere, so they are named here only so the next reader does not attribute them
to this one:

* the five dec1 examples (`count`, `fact`, `pow2`, `sqsum`, `sum`) fail on
  `hx30fr` — `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md`, whose Status
  I corrected the same day;
* `test_formal.py` could not even START, because `audit_step_table` counted a
  `--` COMMENT inside `arm64_step` as a branch. **That one is fixed** on
  `work/formal16-3` (`formal/arm64_proof_gen.py`, `audit_step_table`), and it is
  worth knowing that the job was failing for a reason that named nothing:
  `only in ProofLib []` and `only in _STEP_CONDS []`, i.e. equal sets with
  different multiplicities.

## The next step

`_gen_universal_e2e_cfg` finds its loop contract by shape:

```
loop_check = None
for b in blocks:
    if b["kind"] == "b" and start_to_bi.get(b["targets"][0]) is not None:
        cbi = start_to_bi[b["targets"][0]]
        if blocks[cbi]["kind"] == "cbz":
            loop_check = (cbi, blocks[b]["targets"][0])
            break
```

and `_gen_dec_while_block`'s contract is only built for a `cbz` whose tested
register is the one `loop_test` maps. `wdiff`'s test is `n != 0`, which the
codegen lowers to a **CBNZ** (`n != 0` is not `<= 0`), so the shape above either
finds no `b`-into-`cbz` pair at all or finds one whose condition it declines.
The two questions to answer, in order:

1. What does the emitted CFG actually look like — dump `blocks` with
   `ARMPROOF_DEBUG=1` (the debug print in the `cbz` arm already emits
   `BLOCKS`, `start_to_bi` and `path`), and say whether the back edge's
   terminator is `cbz`, `b`, or something else for `while n != 0`.
2. Whether `_gen_dec_while_block` can state the contract for a `!= 0` test at
   all, or whether `wdiff` needs the `NE`-tested loop model that
   `bugs/FORMAL_arm64_known_proof_gaps.md` §`countdown`/`wge` implies is
   signedness-independent — it says `wdiff` "is NOT affected, because equality is
   signedness-independent, and it passes with no hole", which is a claim about
   the MODEL and is now contradicted by the emitter refusing to build the
   contract for it.

Until then the honest statement is: **`wdiff` is an unexpected failure of the
`formal` suite job on `master`, and the x30 filing's use of it as the passing
control is wrong.**