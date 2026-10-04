# `formal/examples/sum_range.mojo` has no loop contract because its back edge is a CONDITIONAL branch — and no `EXPECTED_FAILURES` entry says so

**Area:** FORMAL (the arm64 proof generator's CFG walk). Found 2026-10-03 on
`work/formal18-6`; measured, not fixed. It belongs to whoever holds
`formal/arm64_proof_gen.py`'s walk, and it is **one arm away** from
`“`formal/examples/wdiff.mojo` has no loop contract on arm64”`, which this branch fixed and deleted.

**Not new, and the prior observation is recorded.** `bugs/FORMAL_proof_coverage_census_2026-10-03.md`
§0.3 already measured this exact refusal against this exact tree:

| item | the census's ledger | this tree, arm64 |
|---|---|---|
| `formal/examples/sum_range.mojo` | `admitted`, 2 holes | `ValueError: unsupported cbz taken continuation to 0x100000330` |

So the refusal is old — `git log -S` puts the `raise` at the 2026-09-23
restructure that created this backend — and what is new here is three things
that doc does not say: **the root cause**, **that the `formal` SUITE job is red
because of it and nothing in the tree records that**, and **that a second doc
still quotes the stale half of the table above**.

## What I ran

```console
$ python3 -c "…" probe_all.py arm64          # every formal/examples/*.mojo through
                                            # compile_formal(prove=True, check=False)
sum_range   FAIL  ValueError: unsupported cbz taken continuation to 0x100000330
```

Identical on **master's tip** (`6ccb36df`) and on this branch's base
(`86d60026`), so neither the last 25 merges nor this branch's commits did it. No
Lean: the refusal is at GENERATION time, so the whole census costs 2 s.

## The root cause, which is the part that is new

The built image, read off `formal/arm64_proof_gen.py`'s own decoder:

```
0x100000300  movz x0, #0 ; mov x20, x0 ; movz x0, #0 ; mov x21, x0    the prologue
0x100000324  cmp x0, x1
0x100000328  b.lt 0x100000330           <- into the body
0x10000032c  b    0x100000374           <- and past it (the loop never runs)
0x100000330  … total += i ; i += 1 ; cmp x0, x1 …
0x100000368  b.lt 0x100000330           <- THE BACK EDGE, and its target is the
                                           block's OWN start
0x10000036c  sub x21, x21, #1 ; b 0x100000374
0x100000374  … ret
```

`_cfg_blocks` therefore reports `0x100000330` as a `cbz`-kinded block whose TAKEN
target is itself, and the walk's conditional-branch arm raises:

```python
# formal/arm64_proof_gen.py:6019
tgt_bi = start_to_bi.get(taken)
if tgt_bi is None or tgt_bi in path:
    raise ValueError(f"unsupported cbz taken continuation to {hex(taken)}")
```

**That edge is the loop.** A `for` loop lowered with the test at the BOTTOM of
the body has a conditional back edge, so "the taken target is a block already on
the path" means *loop again*, not *impossible continuation*.

**The binary is right**, which is what makes this a proof-layer gap rather than a
codegen one:

```console
$ python3 fire.py build --formal --no-prove -o .tmp/sr.aout formal/examples/sum_range.mojo
$ .tmp/sr.aout ; echo $?
45            # 0+1+…+9, and it terminates
```

**And the walk's loop-contract handling is on ONE arm.** The unconditional
`b`-block arm consults `ctx["loop_contract"]` when its target is the loop top
(`formal/arm64_proof_gen.py:5382`); that is what makes `wdiff`, `countdown` and
`wge` generate contracts today — they lower with the test BEFORE the body, so
their back edge is an unconditional `b`. The conditional-branch arm's taken edge,
640 lines down, has no case at all. **`sum_range` and those three are the same
loop contract split across two arm shapes, and only one shape is implemented.**

## Why nothing in the tree records it

`test_formal.py`'s `EXPECTED_FAILURES` holds `fib`, `countdown`, `wge` and
`subscript_var` — **not `sum_range`** — and `tools/suite.py` registers

```python
test('formal', [PY, 'test_formal.py'], j=True, deps=['preflight', 'prooflib'], …)
```

with no `expect=`. So this is an UNEXPECTED failure of a job the registry says
must be green. The census doc saw the refusal and filed it against the CENSUS; the suite job is a different job, and nothing connects the two.

**Two numbers in the tree now disagree and both are quoted.** This doc's §0 table
above says the ledger recorded `admitted, 2 holes`, and
`bugs/FORMAL_arm64_known_proof_gaps.md` still quotes it — "sorries in passing
proofs | 2, both in `sum_range`", with `sum_range` absent from its own
known-gaps row. That doc is `formal18-2`'s claim, so this one does not edit it;
it is named here as the place where the stale half lives. Settling which number
is right is a `git log` on the walk, and it is the first step for whoever takes
this.

## The next step, and the shape of it

Give the conditional back edge the treatment the `b` arm already has. The
question to answer is the one that arm already asks:

* **is the taken target the loop top?** — `ctx["loop_contract"]["cbz_start"]`,
  the same value `:5382` matches on. If so, apply the contract there too.
* **if it is not**, it is a genuine re-entry and the refusal is right. That
  distinction is the whole of the patch; nothing below it needs new work.

Two measurements to take while in there, both cheap:

* `_gen_range_loop` already matches this file's shape (its loop-top block has the
  STP/LDP + CMP-register prefix it looks for), so check whether the contract it
  emits is what this edge needs or whether `while_lt_exit_contract`'s exit
  obligation has to be routed differently. The countdown arm's use site is the
  worked example of a contract being applied mid-walk.
* the ledger's two holes were in `loop_cond_flag`. If the range contract's
  `cond_flag` obligation is what fails to close, the honest outcome is a
  generated proof carrying that hole — which is what the ledger recorded — rather
  than a refusal.

## Reproducing

```console
$ cd "$(git rev-parse --show-toplevel)"
$ python3 -c "
import sys, os; sys.path.insert(0, os.getcwd())
import formal.build as B
try:
    B.compile_formal('formal/examples/sum_range.mojo', output='.tmp/sr.aout',
                     prove=True, check=False)
except Exception as e:
    print(type(e).__name__, e)"
ValueError unsupported cbz taken continuation to 0x100000330
```