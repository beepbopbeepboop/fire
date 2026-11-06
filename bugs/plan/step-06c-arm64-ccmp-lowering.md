# plan/step-06c: lower `if A and B:` (two integer comparisons) to `cmp` + `ccmp` + one `b.cond`
Class: hard      Size: L      Depends: 06a, 06b      Blocks: none
Source: `bugs/FORMAL_arm64_instruction_coverage.md` gap table row `ccmp`; `formal/examples/both.mojo` (`if n > 0 and n < 10:`) and `formal/examples/not_and.mojo` (`if not (n > 3 and n < 30):`) are the corpus witnesses.

## Current state (measured; verified 2026-11-05)
- `formal/arm64_codegen.py::_emit_if` (line 3687) calls `_emit_branch_unless(cond, fail)` (line ~10410). That function handles a bit test, a `x & y` test and a single comparison; for a `BinaryOp` with `op in ("and","or")` it returns False and `_emit_if` falls to `_emit_truthy_word(cond)` (line ~10045) which recurses: each side to X0, `cmp x0,#0`, `cbz`/`cbnz`, join label — each comparison is materialised as a 0/1 with `cset`.
- Single-comparison path to copy: `_emit_branch_unless` -> `_cmp_spec(op, l, r)` (returns `left, right, unsigned_cond, signed_cond, reading`), `_emit_cmp_flags`, `self._signed`, `_record_cond_branch()` immediately before the `b.cond`, `invert_cond`. The `TST`/`CMN` arms (`_emit_branch_unless_and_test`, `_emit_branch_unless_sum_zero`) are the template for adding a new arm: they gate, emit the flag-setter, record the cond branch, emit `b.cond` + `emit_label_rel(false_label, here_offset=-4)`.
- The proof generator's branch-condition proofs assume the flags are `arm64_subs_flags a b` of the LAST compare (formal/arm64_proof_gen.py ~10067-10110, `_hcond_close`: "`arm64_matches_condition cc (arm64_subs_flags a b)`"). A `ccmp` makes the flags `if matches c1 then subs else const`; whether `_hcond_close` closes that is UNMEASURED.
- Flags needed to make condition `c` FALSE when the first compare fails (architectural `#nzcv`, N=8 Z=4 C=2 V=1), computed from the condition definitions: `eq 0, ne 4, cs 0, cc 2, mi 0, pl 8, vs 0, vc 1, hi 0, ls 2, ge 8, lt 0, gt 4, le 0`. (To make `c` TRUE instead: `eq 4, ne 0, cs 2, cc 0, mi 8, pl 0, vs 1, vc 0, hi 2, ls 0, ge 0, lt 8, gt 0, le 4` — only needed by `or`, which this step declines.)

## Decisions already made
- Shape handled: `A and B` where A and B are each a BinaryOp comparison in `self._cmp_conds()` (not `is`/`is not`), both **integer** (no float `reading`, no string kind, `M.string_binary_refusal(...) is None`, no `_refuse_frame_order_operand` hit), and B's operands are **flag-neutral loads or a literal 0..31** (use `self._is_flag_preserving_load(e)` for loads; the existing helper at the ternary lowering, ~14436, uses it for the same reason: evaluating B's operands between the `cmp` and the `ccmp` must not write flags). Everything else keeps the current path.
- Emission: `cmp A.l, A.r` (via the same operand loading as the single-comparison path, left in X0/X1) ; load B.l into X2 (and B.r into X3 unless B.r is a literal 0..31 -> use `encode_ccmp_xn_imm5`) ; `ccmp x2, x3|#imm, #nzcv_false(condB), condA_chosen` ; `_record_cond_branch()` ; `b.<invert(condB_chosen)> false_label`. `condA_chosen`/`condB_chosen` = `signed_cond if signedness else unsigned_cond` exactly as `_emit_branch_if_cmp` picks; each comparison keeps its OWN signedness. `nzcv_false` is the table above keyed by `condB_chosen`.
- `or` is declined (needs the "true" table and a different polarity); recorded in the docstring, not implemented.
- `not (A and B)` is `not_and.mojo`'s shape: only handle it if `_emit_if` already routes a `UnaryOp not` into `_emit_branch_unless` with swapped labels; read first. If not, decline it.
- Overflow traps are unaffected (comparisons do not trap). The refusal checks (strings, frame order) run for BOTH comparisons before anything is emitted.

## Work order
0. Baseline (before any edit), recorded in this file: `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64 both not_and` — expect PASS for both (if either is already red, STOP: that is another bug).
1. Add `_ccmp_false_nzcv(cond: str) -> int` to `formal/arm64.py` next to the encoders (the table above, keyed by `_cond` name), and a unit test in `test_arm64_encoders.py` that checks it against a pure-Python flag evaluator: for every cond and for the returned nzcv, `cond` evaluates false (write the 14-line evaluator from the ARM ARM definitions; do not import the Lean model).
2. `formal/arm64_codegen.py`: new method `_emit_branch_unless_and_cmp(self, cond, false_label) -> bool`, called from `_emit_branch_unless` right after `_emit_branch_unless_and_test` (before the single-comparison arm). Docstring: the shape, the `nzcv` rule, why `or` is declined, why B's operands must be flag-neutral, the 14,455 count.
3. `test_arm64_emission.py`: add `CCMP_CASES` in the style of `CSEL_CASES` (line 73): `(name, source, expected_exit, ("ccmp",))` — the last tuple asserts the mnemonic appears in the disassembly. Cases: `if a < b and c == 0`, mixed signed/unsigned, B false / A false / both true, a literal-31 and literal-32 right operand (32 must fall back to a register), and one that must NOT use ccmp (`a and b` with a call in B) via a `forbid` tuple if the file supports it (read its harness first; add the minimal support if not). Expected values come from CPython, never from the emitted code.
4. Run both backends' differential for those sources: `test_formal_run.py` (find the row that runs one source on both arch and CPython; add the CCMP sources there if that is where `if` shapes are tested) — x86-64 needs no change (it keeps its own lowering; this is instruction selection only).
5. Proof side: `python3 test_formal.py --backend arm64 both not_and` again. Outcomes:
   (a) both PASS -> done with the proof side.
   (b) a proof fails in the hcond step: this is the measurement that matters. Do NOT widen `EXPECTED_FAILURES`. Fix `_hcond_close` (formal/arm64_proof_gen.py ~10067) so it handles flags of the form `if arm64_matches_condition c s.nzcv then arm64_subs_flags a b else k`: after `simp only [arm64_matches_condition, arm64_subs_flags]` the `if` splits with `split <;> simp_all` — implement as an additional `first | ...` alternative, then re-run. If it needs more than that after two attempts, gate the lowering behind a module constant `CCMP_LOWERING = False` (default off), land the rest, and write the measured failure into this file's Status. Partial progress counts (CLAUDE.md).
6. Audit: `python3 tools/arm64_insn_audit.py | grep ccmp` — the encoders must leave the "no lowering emits" list; `ccmp` leaves the uncovered list.

## Do NOT
- Do not emit `ccmp` when B's operand evaluation can write flags (a call, an `adds`-checked add, a `cmp`): the flags set by A would be destroyed and the answer is silently wrong. The test needs a case with a checked `+` in B that must still be correct.
- Do not apply the signedness of A to B.
- Do not skip `_record_cond_branch()`: the proof generator's `_cond_branches` filter uses it to find the `if`'s own conditional branch (record it before the `b.cond`, not before the `cmp`/`ccmp`).
- Do not claim "answers match CPython" from the emitted program alone; compare to `python3` on the same source.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label t -- python3 test_arm64_encoders.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_arm64_emission.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64 both not_and
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
python3 tools/arm64_insn_audit.py | grep -n ccmp
```

## Done when
- [ ] CCMP cases pass in `test_arm64_emission.py` and the differential vs CPython on both backends
- [ ] `both` and `not_and` still PASS (0 sorries), or the lowering is gated off and the measured failure is in Status
- [ ] audit no longer lists the two ccmp encoders as unemitted (or Status says gated)

## Status
- Gated: `formal/arm64_codegen.CCMP_LOWERING = False` (lowering disabled) because proof generation fails for `if A and B:` with CCMP.
- Proof error (arm64 formal): `both.mojo`/`not_and.mojo` failed with `NotImplementedError: unsupported: branch condition value flow (frame/flag unavailable)` from `formal/arm64_proof_gen.py` during condition handling; attempting to extend `_hcond_close` to split CCMP if-forms was insufficient. Gating preserves correctness of the old lowering path.
- Encoders added: `formal/arm64._ccmp_false_nzcv`, tests added to `test_arm64_encoders.py` (all pass). CCMP lowering structure, method, and emission tests added but inactive behind gate.

## If stuck
Write the exact Lean error from the failing example (first 30 lines) and the emitted instruction sequence into this file under "Status", set `CCMP_LOWERING = False`, and stop.
