# Worker brief — proving a scaffolded peephole rule (read this FIRST, then your step file)

You are proving one `sorry`-ed theorem in `lib/Scaffold.lean` and moving it, proved, into
`lib/Peephole.lean`. A worked example is done: step 03b, `peephole_arm64_movz_pair`
(commit message "step 03b: prove arm64/movz_pair"). Read that theorem in `lib/Peephole.lean`
before you start; yours has the same shape.

## The loop (follow it literally)

1. **Check the statement is TRUE before proving it.** These statements were drafted by a first
   wave that never ran Lean. 03b's was false (it said the registers after the second MOVZ equal
   the registers after the first; the second MOVZ overwrites `Xd`). Work the instruction
   semantics out by hand on paper: what does each step write? If the statement is false, FIX the
   statement (keep it as strong as is true), say so in the theorem docstring and in the step
   file's Status, and prove the fixed one. Never weaken a statement just to make it provable
   without saying so.
2. **Prove it in a scratch file first.** Do not edit the library until the proof compiles:

       cd lib && LEAN_PATH=. ../.pixi/envs/default/bin/lean /tmp/mine.lean

   where `/tmp/mine.lean` starts `import ProofLib` / `import Peephole` (and `import X86` for x86)
   and contains your theorem. `lib/*.olean` must be current: if the library is stale run
   `python3 -c "import formal.lean as L; L.ensure_library(L.find_lean(), 'lib')"` once (about 5
   minutes). Never run two library builds at once.
3. **Move it.** Put the proved theorem (and any helper lemma) into `lib/Peephole.lean`
   immediately BEFORE the block comment `/-! ## Design note (x86_64/imm_zero)`. Delete the theorem
   from `lib/Scaffold.lean` (only that file may contain `sorry`; `Peephole.lean` must have none).
   Delete its row from `formal/proof_gaps.py::SCAFFOLD_HOLES`.
4. **Check:** `python3 -c "import formal.lean as L; L.ensure_library(L.find_lean(), 'lib')"`,
   `python3 test_formal_proof_gaps.py` (5/5), `python3 test_formal_peephole.py` (all OK).
5. **Doc:** change line 2 of your step file to `**Status: DONE <date> (measured).** ...` saying
   what was proved, whether the statement had to be corrected, and the three results above.
   Then `python3 tools/plan_index.py --write`. Commit. Do NOT edit `formal/peephole.py`'s rule
   lists: promoting the rule from SCAFFOLDED to live is step 05a/05b, not yours.
6. Before you finish, `git fetch` and rebase onto master: several workers add theorems to the
   same files; resolve conflicts by keeping BOTH sides.

If you cannot finish: leave the theorem in Scaffold with its ledger row, commit any helper
lemmas you did prove (in `Peephole.lean`, sorry-free), and write exactly what blocked you into
the step file under a `Blocked` heading with the goal state. Do not leave a half-edited library.

## Facts about the model you will need

* **ARM64:** `arm64_step s code` does NOT advance `pc`; `arm64_steps s code n` does (`+4` per
  step). That is why the second step in `hpair` is from `{ s1 with pc := s.pc + 4 }` and returns
  `{ s2 with pc := s.pc + 4 }`. The lemmas `arm64_steps_one_seq` / `arm64_steps_two_seq`
  (Peephole.lean) turn step facts into the `arm64_steps` clauses.
* One-step lemmas exist: `arm64_step_movz64`, `arm64_step_ldr64`, `arm64_step_str64`,
  `arm64_step_add_imm64` (Peephole.lean). Use them as `have e := arm64_step_X s code pc w hpc hread h hrt`,
  then `rw [hs1] at e` and `Option.some.inj e` to get `s1 = ...`.
* `arm64_set_reg i s v` is a `match` on `i`; prove facts about it with `unfold arm64_set_reg;
  split <;> simp_all` (this closes `arm64_set_reg_set_reg_same`). `arm64_set_reg_pc_congr`
  commutes a `pc` update with a register write (use `←` to push a `with pc` inward).
* Memory: `mem_read_after_write_u64` (ProofLib, `@[simp]`) = reading what was just written;
  `mem_write_u64_idem` (Peephole) = writing the same value twice.
* **x86:** `x86_step` DOES advance `rip` (by the instruction length). Lemmas are in `lib/X86.lean`
  (named in the theorem's comment block in Scaffold.lean). Register helpers
  `x86_get_reg_set_reg_other`, `x86_set_reg_self` are in Peephole.lean.
* `{ s with pc := p }` elaborates to a 48-field record in goals; do not `simp` it open. Rewrite
  with `rw [..]` using equations about `arm64_set_reg`, or `apply congrArg some` and
  `refine Eq.trans ?_ hs2'.symm` to align both sides, then finish with a small lemma.
* There is no Mathlib: `omega`, `simp`, `bv_decide`, `decide`, `rcases`, `split` are available;
  `interval_cases`, `split_ifs`, `norm_num` are NOT. For `x = 0 ∨ x = 1 ∨ ...` use
  `rcases (by omega : x = 0 ∨ ...) with rfl | ...`.
* If `rw` says "did not find an occurrence", look at the goal: the pattern you wrote may be
  syntactically different (a `have __src := ...` form, a flipped equation). Fix the direction
  with `←`, or restate with `show`/`have key : ... := by` and finish by `exact`.

## Rules of the house

* Never `git checkout -- <file>` / `git restore` an edited file (destroys work). Use `git stash`.
* Never kill processes. Do not run `make gate` or the full test suite.
* One theorem per commit when possible, with a message that says what was proved.
* Report at the end: which theorem, whether the statement was corrected (and how), the exact
  commands you ran and their results.
