# An arm64 conditional whose immediate is on the LEFT never elaborates

**Area:** FORMAL, `formal/arm64_proof_gen.py` — the `B.cond`/`CBZ` block's
`hcond` obligation. Found 2026-10-05 on `work/formal55-match-statements`, while
checking that the `match` lowering's Lean model carries the lowered compares
(`test_formal_match.py`'s proof section).

## Status 2026-10-08 (`work/formal178-docs`): the defect is FIXED at the root,
## and it was TWO defects, neither the one §2 diagnoses.

Both spellings now generate the same proof shape; on **x86-64 both elaborate**
(measured, `check_proof_cached`: `if n == 0:` and `if 0 == n:` each `ok=True`,
0 errors, 2 pre-existing `sorry`s in the shared library). What follows is what
was actually wrong, because §2's reading ("the reconstruction follows the
AST's operand order rather than the encoding's") is not it.

1. **The `hcond` mismatch the doc measured was `_taken_dead` on a `B.cond`.**
   `_gen_universal_e2e_cfg`'s statically-dead-taken-arm shortcut
   (`_cbz_reg_const` + `_taken_dead`) closed the taken arm of ANY branch by
   `exact absurd hc_N hne_N` with `hne_N : arm64_reg r s ≠ 0`, where
   `r = w & 0x1f`. That `r` is a register only for `CBZ`/`CBNZ`; on a `B.cond`
   it is the condition code (bits 3:0) and the tested value is the FLAGS, so
   `hne_N` is never the negation of `hc_N : arm64_matches_condition … = true`
   and Lean rejected the whole proof with `Application type mismatch`. It fired
   for `if 0 == n:` only because that spelling happened to leave a constant in
   the register the scan named. Fixed: the scan runs only for `_bidx == 16`
   (CBZ). Pinned by
   `test_formal_call_proof_gen.py::TestACompareWithTheImmediateOnTheLeft::
   test_a_flags_branch_is_never_closed_by_a_register_hne`, verified red against
   the pre-fix generator.

2. **The residual proof failure was the `eval_eq_mojo` bridge, and it is the
   operand-order half §3 asks for.** A comparison is rendered twice — by
   `_cmp_term_t` (model and `by_cases` split) and by `_expr_ast` (the AST the
   bridge evaluates). With the literal on the left the split was `(0 = n)`,
   which `simp` turns into the rewrite `0 → n` (it will not rewrite a variable
   to a numeral), so the `by_cases` hypothesis never reduced `n` and the bridge
   could not close. Fixed by normalising an EQUALITY so a bare literal is on
   the right, in BOTH renderers (one edit each; `x86_64_proof_gen` shares both,
   so this is both backends). Pinned by the same class's
   `test_the_bridge_normalises_and_the_spellings_agree`.

**What is still open, and it is NOT this bug.** On arm64 the same two programs
still do not elaborate end to end, but so does the previously-fine `if n == 0:`
— the failures are shared and pre-existing: a `native_decide` in a `TBZ` step
lemma whose asserted proposition is false (`main_sr_231`/`main_sr_232`,
`… >>> 5 &&& 16383 &&& 8192 = 0`), a downstream `unsolved goals`, and
`maximum recursion depth has been reached` in a `runs` certificate. None is
reachable from the operand order, and all three reproduce with the fix reverted
(so they are the tree's, not this change's). They are why the arm64 end-to-end
acceptance of §"The next step" still cannot be run; they belong to a separate
claim in the `TBZ`/step-table area and are named here rather than silently
folded into this one.

## 1. What I ran and what I saw

Two programs that differ only in which operand of the comparison carries the
literal. Generated and checked through `formal/lean.py::check_proof_cached`
(`repo_root` = this worktree, `lib/ProofLib.olean` present):

```sh
python3 - <<'EOF'
import sys, os, tempfile
sys.path.insert(0, '.')
import formal.build as fb
from formal.lean import check_proof_cached
tmp = tempfile.mkdtemp()
for name, p in {
  "lit_right": 'def main() -> Int:\n    n = 3\n    if n == 0:\n        return 10\n    else:\n        return 20\n',
  "lit_left":  'def main() -> Int:\n    n = 3\n    if 0 == n:\n        return 10\n    else:\n        return 20\n',
}.items():
    src = os.path.join(tmp, name + ".mojo"); open(src, "w").write(p)
    r = fb.compile_formal(src, arch="arm64", output=os.path.join(tmp, name),
                          prove=True, check=False)
    print(name, check_proof_cached(r["proof_path"], repo_root=os.getcwd())[:1])
EOF
```

| source | arm64 proof |
|---|---|
| `if n == 0:` | **ok**, 1 `sorry` |
| `if 0 == n:` | **`Application type mismatch`** ×2, 0 `sorry` |

Both IMAGES are correct and both exit with CPython's answers — this is a proof
failure only, on a program the compiler already builds and runs.

The error, at the `B.cond` block's `by_cases` (generated line 2538 onward):

```
by_cases hc_4 : arm64_matches_condition 1 s_4.nzcv = true
·
  have hne_4 : arm64_reg 1 s_4 ≠ 0 := by
    simp only [hsid_4, …, arm64_reg, arm64_set_reg, Arm64State.init]
    simp (disch := decide) [mem_read_after_write_u64, …]
    all_goals native_decide
  exact absurd hc_4 hne_4          -- ← Application type mismatch
```

`hne_4` is proved from the STATE ALONE (`simp only [… arm64_reg,
Arm64State.init]`), so it says "register 1 is not 0" with no reference to the
flags. The goal `exact absurd hc_4 hne_4` needs "the condition held" to imply
"register 1 IS 0", and the only thing that carries that is `s_4.nzcv` — which
nothing in the `simp only` set unfolds. So the obligation closes by
`absurd` with a hypothesis that was never connected to the flags.

**This is the same failure as
`FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`**, whose
§"never reduces to an order" says exactly this: `arm64_matches_condition N
(arm64_subs_flags …)` has to reduce to an order for the `hcond` obligation to
close, and where it does not, the generated proof cannot be rescued by `simp`.
That doc's measured program happens to put the immediate on the right, which is
why the two look like different bugs; the mechanism is one.

## 2. Why the operand order reaches the proof

`formal/arm64_codegen.py::_cmp_spec(op, left, right)` decides which operand is
the immediate and which is a register, and the emitted `CMP` therefore differs
between the two spellings (`cmp w0, #0` against `cmp w0, w1` — both are legal
encodings of the same test). The proof generator reconstructs the source-level
condition from the AST (`_cond_nodes` → `_COND_LEMMA`) and from the emitted
block, and the reconstruction of `arm64_matches_condition`'s ARGUMENTS evidently
follows the AST's operand order rather than the encoding's, so for the
immediate-on-the-left spelling the flag predicate it hands Lean is not the one
the flags carry.

## 3. The next step

Make the reconstruction order-insensitive rather than patching one spelling:

* `arm64_matches_condition`'s operand list should be built from the EMITTED
  compare (what `_cmp_spec` decided), not from the AST's `left`/`right`. The
  generator already knows the encoding — that is what `_cond_nodes`' callers
  match against the PC the codegen named — so this is a matter of reading the
  same table the emitter read.
* Or, if the reconstruction must follow the AST, `simp only` has to carry a
  lemma per (condition, operand order) pair, which is a bigger change: the flag
  predicate's arguments come from `arm64_subs_flags`, so a lemma stated for
  `n == 0` is not the lemma for `0 == n` until the model normalises the two.
  Normalising at the MODEL (`arm64_matches_condition` comparing an
  immediate-left pair to its immediate-right twin) is the smaller of the two.

Whichever is chosen, the acceptance test is the table above: both spellings
elaborate, and the `by_cases` obligation closes from the flags rather than from
the state.

## 4. Why it is worth fixing rather than avoiding

The `match` lowering in `formal/build.py::_rewrite_match_statements` emits
`SUBJECT == PATTERN` **specifically so this gap cannot bite it** — see that
function's `_lower_one_case` docstring for the measurement, and
`test_formal_match.py`'s proof section, which fails if the order is swapped
back. But avoiding one caller is not a fix: the gap is reachable from any
program that writes `if 0 == n:` or `if CONST == x:`, and the second of those
is idiomatic in the corpus this backend compiles (`bugs/FORMAL_arm64_known_proof_
gaps.md` is the census of what else is in that family).