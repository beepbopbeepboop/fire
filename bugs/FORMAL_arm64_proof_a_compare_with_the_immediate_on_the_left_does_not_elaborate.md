# An arm64 conditional whose immediate is on the LEFT never elaborates

**Area:** FORMAL, `formal/arm64_proof_gen.py` — the `B.cond`/`CBZ` block's
`hcond` obligation. Found 2026-10-05 on `work/formal55-match-statements`, while
checking that the `match` lowering's Lean model carries the lowered compares
(`test_formal_match.py`'s proof section). **OPEN.** Not this branch's claim:
the generator is arm64's, and the operand order is a property of the SOURCE.

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