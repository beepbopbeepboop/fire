# `formal/examples/sum_range.mojo` has no loop contract because its back edge is a CONDITIONAL branch — and no `EXPECTED_FAILURES` entry says so

**Status (2026-10-04, `work/formal21-6`): the GENERATION refusal is FIXED at the
root cause — the back edge is discharged by a bottom-tested loop contract, and
the doc's "next step" was right about what to ask and wrong about how many
things had to be asked. The proof now generates on arm64. It still does not
TYPECHECK, for a reason in the walk's SHARED conditional-branch machinery that
this branch did not take: see §0 and the second doc.**

**Area:** FORMAL (the arm64 proof generator's CFG walk). Found 2026-10-03 on
`work/formal18-6`; measured, not fixed. It belongs to whoever holds
`formal/arm64_proof_gen.py`'s walk, and it is **one arm away** from
`bugs/FORMAL_wdiff_has_no_loop_contract.md`, which this branch fixed and deleted.

## 0. What landed, and what is still open

**Fixed: `ValueError: unsupported cbz taken continuation to 0x100000330` is
gone, and it is gone at the cause.** The doc's §"The root cause" is confirmed
exactly — a `for`-range loop's back edge is a conditional branch, and the walk
asked "is this the loop top?" only in its `b` arm — and the discovery was the
half this doc did not name:

> `_gen_range_loop` was written for a shape the emitter **has not produced
> since the preheader landed**.

`arm64_codegen`'s `_emit_while` puts a `for`-range loop's emptiness test in a
PREHEADER, so the body, the counter increment, the comparison and the back edge
are ONE `cbz`-kinded block whose taken edge targets its OWN start, and the
generator's loop discovery — "a `b` block whose target is a `cbz` block" — has
no answer for it. Measured over every `.mojo` in `formal/examples/` and
`formal/hostmods/`: one self-looping `cbz` block for `sum_range`, and **no
top-tested range loop anywhere**, which is why the contract generator matched
nothing and the walk had nothing to apply. That is the whole of "the loop
contract is on ONE arm": the arm was right about the question and the loop was
not in the shape it was asking about.

The commit adds `while_lt_exit_contract_bottom` to `lib/ProofLib.lean`
(`while_lt_exit_contract` for a loop whose test is at the bottom: no condition
prefix, the branch's TAKEN edge is the loop again, and an entry obligation
that the counter is still below the bound), rewrites `_gen_range_loop` for the
shape the emitter produces — including composing the TWO-block exit path out of
each block's own certificate — and makes the `cbz` arm ask the question the
`b` arm already asks. The back edge's register chain and terminal value flow
moved out of the `b` arm into `_emit_range_back_edge_tail`, shared by both.

**Still open, and it is a different bug: the generated proof does not
typecheck.** One Lean error, in the walk's `hcond` obligation for the loop's
PREHEADER — the comparison's operand is read through a spill slot stored two
blocks earlier, the chain emits no flag lemma for a `B.cond`, and `bv_decide`
returns a "potentially spurious counterexample" over its own abstraction.
Filed, with the reproduction and the next step, as
`bugs/FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`. It
is not in the loop contract and it is not this branch's to take: `hcond` is
emitted for every conditional branch, so appending a `sorry` to that chain
would convert other programs' build failures into admitted obligations.

The generated proof also carries **four admitted `sorry`s** — the frame
obligations the loop's body run and exit path owe, stated where they are used
rather than discharged. That is this emitter's established shape
(`_COND_ARITH_DEFAULT`, the `-- TODO(range)` leaves) and the honest outcome
this doc's §"The next step" predicted: "a generated proof carrying that hole …
rather than a refusal". `test_formal.py`'s hole census reports all four, so
they are counted rather than hidden.

**Verified:** `python3 test_formal_call_proof_gen.py` — 61 passed, 0 failed,
including three new rows that pin that `sum_range` generates, that its proof
carries `while_lt_exit_contract_bottom`, and that the loop top on the IMAGE is
the self-looping block the contract is generated from. `python3 -c` over every
`formal/examples/*.mojo` with `prove=True, check=False`: **48 of 50 generate**,
and the two that do not are `subscript_var` (in `EXPECTED_FAILURES`) and
`wide_recv` (a semantic-model refusal in code-generation territory), both
unmoved by this change — it was 47 of 50 before it.

**`test_formal.py`'s `sum_range` row is still red**, for the `hcond` reason
above. So this document stays: the job it names is still not green.

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