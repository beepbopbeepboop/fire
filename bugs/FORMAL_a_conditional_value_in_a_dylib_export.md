# A conditional VALUE in a dylib export: the block layer already takes it, and the cost is the certificate

**Area:** FORMAL — the dylib contract emitter (`formal/arm64_codegen.py`'s
`_dylib_contract_proof` / `_dylib_spec_lean`) and the export walk
(`formal/arm64_proof_gen.py`'s `_gen_run_cert`).

**This document replaces two documents and hands two subjects to the documents
that own them.** It exists because the measurement that decides *whether a
dylib export can be proved at all* was split across three files, none of which
owned it, and a reader could not tell which half was settled:

| what | where it lives now |
|---|---|
| the block layer ACCEPTS a conditional value — measured, fixed, pinned | §1 below |
| modelling `CSEL` turns a NAMED OBLIGATION into a build failure, and it is not a budget question | §2 below |
| the `hprior_*` cost centre and the certificate's Lean bound | **`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`** (live claim) |
| the `CSEL` model row itself | **`FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`** (live claim) |
| the loop-fuel obligation (`OPUS-4`) | **`FORMAL_dylib_export_loops_and_frame_bounds.md`** (live claim) |

The two documents it replaces were `FORMAL_dylib_block_layer_is_not_the_ceiling.md`
and `FORMAL_csel_in_the_model_costs_a_ternary_export_its_whole_proof.md`, both
deleted 2026-10-05. A third, `FORMAL_contract_work_handoff.md`, was a finished
task's handoff whose §3 landed and whose §4 belongs to the loop-fuel document; it
was deleted in the same commit and `OPUS.md`'s pointer to it was repointed.

**Nothing here is new.** Every number is attributed to the pass that took it, and
the two open subjects are named rather than restated, because both are held by
live claims and a second copy of either is a document that will be right until
the claim lands and then wrong.

---

## 1. The block layer is not the ceiling, and a conditional value is not a branch

The starting premise was that a dylib export body with a branch is not "one
function of one state", which is what `Refine.Block.step` asks for, and that the
block layer was therefore the ceiling on what could be proved. **Measured: the
block layer was not the ceiling, and the ceiling was a substring test.**

### 1.1 The defect, and what it cost that was reachable

`_dylib_contract_proof`'s gate was

```python
if any("if " in _body_of(i) for i in range(m)):
    return ""
```

— a substring standing in for *one function of one state*. The two are different,
both spellings are real, and a substring cannot tell them apart:

| a step that CHOOSES A VALUE | a step that CHOOSES A PC |
|---|---|
| `CSET`: `some (arm64_set_reg rd s (if arm64_matches_condition c s.nzcv then 1 else 0))` — one `some`, so `arm64_step` says it is one function of one state | `B.cond`/`CBZ`/`TBZ`: the model answers `if c then some A else some B`, so there is no single `some` to strip |

So the check refused every export whose code contained a `cset`, which is a
**live, already-reachable** loss and not a hypothetical one about `CSEL`:

```
$ cat .tmp/p/csetval.mojo
def csetval(n):
    var b = not n          # CMP + CSET — branchless, two instructions
    var m = n * 3
    return m
```

`arm64_codegen.py` emits `cmp` + `cset` for a `not` in VALUE position
(`_emit_truthy_word`, then `encode_cmp_xn_imm` + `encode_cset_xd_cond`) and never
branches. The image is 23 instructions, the eighth is `cset x0, eq`, and it
computes `n * 3` — run through the dylib: 0/15/42/300 for `n = 0/5/14/100`,
against the same values from the branchless twin with the `not` deleted.
`_dylib_contract_proof` returned the **empty string** for it.

**The fix asks the MODEL's shape instead of the text.** `arm64_step` returns
`some <state>` exactly when the step is one function of one state, so `_step_rhs`'s
own `some` prefix is the discriminator — and it is the same prefix `_body_of`
already reads, so there is no new encoding to keep in step. The `pc_writes`
discipline is unchanged, so a branch in any position but the last is still
declined and the last may still be the `ret`.

**Measured after: the same export gets a PROVED contract** — `bodyCert`,
`agrees_of_body`, `hreg` — and the emitted file checks clean with **0 holes** in
**7.5 s / 1.6 GB** through `formal/lean.py`. Pinned by `test_formal_dylib.py`'s
`a conditional value is not a branch`, which asserts all three claims at once: the
image's answers, a PROVED `agrees_of_body` for the `cset` export, and — the
control — a *named* `_spec` obligation and **no** contract for a body with a real
`B.cond` in it. That last one matters: "a spec exists" and "a contract was proved"
are two different facts, and only the second is worth anything.

`test_formal_dylib.py` is 25/25.

### 1.2 `_dylib_spec_lean` renders a condition, so rows 3/4/5 have a spec at all

`TernaryExpr`, `and`/`or` and a comparison read as a **condition** are now
rendered. Before this, three of the six export bodies in §2's table derived **no
spec**, which is a different failure from the one they hit next and worth
separating: a body with no spec has nothing to check against, so the export is
declined for want of a claim rather than for want of a proof.

### 1.3 What is left here, and it is one row

* **Rows 3/4/5 of §2's table still need the `CSEL` model row.** That row is
  **not** this document's and **not** free: it is deliberately ABSENT from
  `_STEP_CONDS` with a long comment saying why (`check_step_conds` requires the
  table and `arm64_step` to be the same set, so a row with no model branch is a
  generator describing a CSEL's effect while the function being proved takes no
  step for that word), and the model branch is claimed by
  `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`.
  **What §1 landed is that the block layer will already accept it when it
  arrives**: a `CSEL` is `some (arm64_set_reg rd s (if … then … else …))`, which
  is the `CSET` shape above — one `some` around a conditional value and no `pc`
  write anywhere.
* **The loop (row 6) is untouched** and still needs the per-block `pc` function.
  That is `OPUS-4` in `FORMAL_dylib_export_loops_and_frame_bounds.md`.

---

## 2. Modelling `CSEL` turns a NAMED OBLIGATION into a BUILD FAILURE

This is the measurement that decides whether the CSEL row can be landed, and it
is a **build failure, not a named obligation** — strictly worse than the
obligation it replaces, which is the whole reason the row is not landed.

### 2.1 The five bodies, with `CSEL` in the model

Six export bodies, each built as its own dylib with `fire.py dylib --formal`
(so the contract AND the termination proof are both emitted), with `CSEL`
present in `arm64_step` / `_STEP_CONDS` / `_step_rhs`:

| body | instructions in the export extent | verdict |
|---|---|---|
| `return n * 3` | 15 | `total_of_halts` — proved |
| `return (n * 3) and (n + 1)` | 26 | `total_of_halts` — proved, 1.9 GB |
| `return (n if n > 3 else 0) * 3` | 26 | `total_of_halts` — proved |
| `return (n * 3) if n else 0` | **24** | **`error: (kernel) excessive memory consumption detected`** |
| `var i = n` / `while i > 0: i -= 1` / `return i * 3` | 27 | NAMED obligation (unchanged — a loop is not one block) |

```console
$ python3 fire.py dylib --formal -o row3.dylib row3.mojo
formal dylib: proof check failed: row3_proof.lean:3200:8: error: (kernel)
excessive memory consumption detected
```

`3200` is `dylib_export_0_tri_halts`, the walk theorem `_gen_run_cert` emits.
Re-run outside the gate with `lean -M 16384` under a 14 GB ceiling, it was killed
again. **Baseline for the same body before `CSEL` was modelled: 1.7 GB and one
named obligation, exit 0.**

**The failing body is the SHORTEST of the four that reach the walk**, and the
failure is not a marginal overshoot. The two that pass differ from the one that
fails in which condition code they use — row 3's is `csel x0, x0, x1, eq`
(code 0, `z = 1`) and row 4's is `csel x0, x16, x0, ne` (code 1, `z = 0`) — but
**nothing here should be read as "row 3 is over the line and row 4 is under
it"**: both are within a couple of instructions of each other and the margin is
not characterised.

### 2.2 Two negative measurements, so nobody re-tries them

* **Raising `-M` does not help.** This is a blowup, not a budget question. The
  same argument §1 of `FORMAL_dylib_export_loops_and_frame_bounds.md` records for
  `hreg`.
* **The condition's SHAPE is not the cost.** Adding `arm64_matches_condition` and
  `arm64_subs_flags` to that goal's `unfold_terms` list — so the condition
  becomes a literal `if 0 = 0 then … else …` and reduces immediately — changes
  row 3 by nothing measurable: same error, same three sites, 6.1 GB peak. **The
  cost is that a conditional VALUE makes the composed state a function of the
  flags, and every later `simp` goal then has to carry that.**

### 2.3 Where the cost is NOT

Inside `tri_halts` there is exactly one goal that unfolds the WHOLE composed
state — `hx30_0` — and it is the obvious suspect:

```lean
have hx30_0 : (dylib_export_0_tri_walk_b0_qS23 ({ Arm64State.init n … })).x30
    = UInt64.ofNat 4294967984 := by
  simp only [dylib_export_0_tri_walk_b0_qS0, …, dylib_export_0_tri_walk_b0_qT23,
             arm64_reg, arm64_set_reg, Arm64State.init]
  simp (disch := decide) [mem_read_after_write_u64, …]
```

**It is not the cost.** Every generated proof with the final theorem REMOVED —
every block cert, every `qS`/`qT` chain, **all 32 `hx30` goals**, all 144
`hprior` goals' statements — checks in **23.1 s at 2.5 GB**; the theorem's
STATEMENT alone on top of that is free; the whole file OOMs at 6.1–6.4 GB after
202–299 s. So rewriting the `hx30` goals as per-step `rfl`s is real work against
a goal that is not the cost, and two earlier prescriptions that target exactly
that are wrong for this reason.

**The cost is `hprior_*`**: 48 / 144 / 384 / 960 at two / three / four / five
conditional branches (×3.0, ×2.67, ×2.5 — the only row that is not a doubling),
emitted once per (PATH, prior block, variable) and each proved by unfolding that
block's whole composed state. There are already 9 `hprior` facts per `hx30` at
three branches **without any `CSEL` in the image**, so a conditional value makes
each of those simplifications carry one more case rather than making more of
them. The full analysis, the 88–97 % duplicate measurement, and what it means
are in `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`, which is
where a fix belongs; a 24-instruction export with **no `CSEL` in it at all**
already fails the same way, which is what makes that the right document and this
one not.

### 2.4 What has landed since, and what is still open

`hprior` sharing — one memo per path rather than a global one — **landed
2026-10-04** and is worth 80× fewer facts at five branches, with the growth per
branch going from ×3.0 / ×2.67 / ×2.5 to **×2.0** (the number of paths, which is
the part that is not re-derivation) and the distinct statements unchanged at
6 / 8 / 10 / 12. The 80× is the ceiling and is **not** reached, because
cross-path sharing would be unsound: `s_{pb}` is REBOUND per path, so a fact
about `s_8` proved on one path is about that path's `s_8`.
`test_formal_call_proof_gen.py`'s `TestNestedConditionFactSharing` holds the memo
to that — one check fails if a fact is proved twice in a scope, one if a fact is
USED where it was not proved, one if the growth goes above ×2.2 again.

**So the open question is exactly one sentence, and it is a measurement nobody
has taken:** *does the sharing let a three-branch export build a proof at all?*
The table above is **emission**, and the certificate's cost is the **kernel's**,
so it cannot be answered without a Lean run — through `formal/lean.py::run_lean`,
with a `MEMLIMIT_GB` **above 8**, because `lib/ProofLib.olean`'s own build peaks
at **7.82 GB** (`formal/lean.py`'s measured table) and a light worker with an 8 GB
ceiling cannot rebuild the library at all. Budget for that before starting rather
than discovering it at the end.

**The dependency runs the other way**, which is why this is worth the memory:
`FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md` §4 lists
the certificate as the thing to solve before the CSEL model row can land. **So
the certificate is on the critical path of a claim somebody else holds.**

---

## 3. Reproducing

| what | how |
|---|---|
| the five bodies, with and without `CSEL` | `python3 fire.py dylib --formal -o <out>.dylib <body>.mojo`, per body. Needs `MEMLIMIT_GB` > 8 for row 3 |
| `hprior_*` and `hx30_*` counts per branch | `python3 tools/formal_hprior_census.py <emitted>.lean` — counts the emitted statements, **no Lean run involved**, which is what makes the emission/cost split cheap to explore |
| the `some`-prefix discriminator | `formal/arm64_codegen.py::_dylib_contract_proof` / `_step_rhs`, and `test_formal_dylib.py`'s `a conditional value is not a branch` |
| the sharing growth bound | `python3 test_formal_call_proof_gen.py` (`TestNestedConditionFactSharing`) |
| the cost centre | `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` §2 and §6 — the 23.1 s / 2.5 GB method |
| `timeout` does not exist on this machine | run `lean` directly and read the exit code; see §6 of the handoff this document replaces, which is why it is repeated here |