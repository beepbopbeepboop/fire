# plan/step-07b: lower `a if c else ~a` to `csinv` (and `+1` / `-a` to `csinc`/`csneg` where no overflow trap is lost)
**Status: DONE 2026-11-07 (measured; found already landed by the plan wave, untested until now).** `_csel_family_shape` / the `_emit_csel_ternary` fast path exist and are correct on the machine: `f(n,c) = t if c != 0 else ~t` returns CPython's answer on arm64 AND x86-64 (exit 97 for n=10), the arm64 image carries exactly ONE CSINV word (`(w & 0xffe00c00) == 0xda800000`); csinc/csneg are gated on `int_overflow_traps` so signed `T+1`/`0-T` keep the CSEL path (absval stays on CSEL). `test_arm64_emission.py` 10/10, `test_arm64_encoders.py` 932/932, `test_formal.py --backend arm64 csinv_ternary` PASS with 0 sorries (constant condition). NOT proved: the input-dependent variant `t if n > 5 else ~t` generates a proof ending in one `walk-terminal` sorry (the generator's shared two-branch value-flow limit), so the example keeps a constant condition and says why. Not added: unsigned/narrow csinc/csneg emission tests (the harness has no typed params) -- left as the follow-up if anyone needs them.
Class: hard      Size: M      Depends: 07a      Blocks: none
Source: `bugs/FORMAL_arm64_instruction_coverage.md` (CSEL family); `formal/examples/absval.mojo` is the natural `csneg` shape and is step-28's example.

## Current state (measured; verified 2026-11-05)
- Ternary lowering: `formal/arm64_codegen.py::_emit_csel_ternary(self, expr)` (line 14436), fields `expr.condition`, `expr.then_val`, `expr.else_val`. Fast path when both arms satisfy `self._is_flag_preserving_load(...)`: `_emit_truthy_word(cond)` ; `cmp x0,#0` ; eval then -> X0 ; `mov x1,x0` ; eval else -> X0 ; `csel x0, x1, x0, ne`. Otherwise a spill path through `stp/ldp`.
- `+`/`-` on signed 64-bit results are overflow-TRAPPED: `formal/model/layout.py:4202 int_overflow_traps(op, result_type, *, pointer_arith=False)` (True for a signed-64 result). A `csinc`/`csneg` lowering of `a + 1` / `0 - a` would WRAP silently where the current lowering traps at `INT64_MAX` / `INT64_MIN`. `~a` never overflows.
- `encode_csinc_xd_xm_cond`, `...csinv...`, `...csneg...` are unemitted until this step; `unary ~` is lowered at `formal/arm64_codegen.py:4391` (`if expr.op == "~"`).
- UNVERIFIED — worker must check first: whether the AST nodes compare structurally (`==`). Run `grep -n "dataclass\|__eq__" fire_compiler.py | head` and `python3 -c` building two identical `NameExpr`s; if they do not compare equal, write `_same_pure_expr(a, b)` (recursive over `NameExpr`/`IntLiteral`/`BinaryOp`/`UnaryOp` with field comparison) in `arm64_codegen.py` and unit-test it.

## Decisions already made
- Shapes (all require `then_val` to be a pure flag-preserving load per `_is_flag_preserving_load`, and `else_val` to be built from the SAME expression `T = then_val`):
  1. `T if c else ~T` -> `csinv x0, x0, x0, ne`. Always allowed (no trap).
  2. `T if c else T + 1` -> `csinc x0, x0, x0, ne`. Allowed ONLY IF `not M.int_overflow_traps("+", result_type)` (unsigned or narrow type); otherwise declined with the existing path.
  3. `T if c else 0 - T` (and `-T`) -> `csneg x0, x0, x0, ne`. Allowed ONLY IF `not M.int_overflow_traps("-", result_type)`; otherwise declined. (So `absval.mojo`, a signed `Int`, stays on the CSEL path; that is correct, because `0 - n` traps at `INT64_MIN` today.)
- Emission order (all three): `_emit_truthy_word(cond)` ; `cmp x0,#0` ; eval `T` into X0 (a load: flags preserved) ; `csinv|csinc|csneg x0, x0, x0, ne`. Rd = Rn = Rm = X0: "if ne then Xn else f(Xm)" with Xn = Xm = T. Verify the operand order against the encoder docstrings and the hardware (test below), do not trust this sentence.
- Result type comes from `self._ttype(expr)`/whatever `_emit_binop` uses to ask `int_overflow_traps`; copy that call, do not invent a second predicate.

## Work order
1. Add `_csel_family_shape(self, expr)` returning `("csinv"|"csinc"|"csneg", T)` or None, implementing the three shapes and the trap gates. Docstring states the measured counts (csinc 3,255, csinv 483, csneg 362) and WHY csinc/csneg are gated.
2. In `_emit_csel_ternary`, at the top after the docstring: `shape = self._csel_family_shape(expr); if shape: emit as above; return`.
3. `test_arm64_emission.py`: `CSEL_FAMILY_CASES` in `CSEL_CASES` style, expected exits from CPython: `~` ternary true/false arm (negative and positive T); `T+1` and `0-T` on an UNSIGNED/narrow typed value if the harness supports typed params (read how other cases type values; if the emission harness is untyped, test the gate with a typed `.mojo` example via `test_formal_run.py` instead); and a SIGNED `T+1` / `0-T` case asserting the mnemonic is NOT `csinc`/`csneg` (use the harness's forbid-mnemonic facility, adding it minimally if absent) and that `INT64_MAX + 1` still traps.
4. Differential on both backends via `test_formal_run.py` (add the sources next to the existing ternary rows; x86-64 keeps its own lowering and must agree on the answers).
5. Proof side: `python3 test_formal.py --backend arm64 <stems of examples containing a ternary on `~`>` — `grep -ln " if .* else ~" formal/examples/*.mojo`; if none exist, add `formal/examples/csinv_ternary.mojo` (+ expected output convention of the neighbouring examples) so the proof path is exercised.
6. Audit: `python3 tools/arm64_insn_audit.py | grep -E "csinv|csinc|csneg"` — only the ones actually emitted leave the unemitted list; a shape that stays declined must be named in this file's Status with the reason (the gate).

## Do NOT
- Do not lower signed `T + 1` / `0 - T` to csinc/csneg "because it is one instruction": the trap is behaviour (`FORMAL_integer_overflow...` family) and the proof model's `int_overflow_traps` is the shared predicate.
- Do not compare AST nodes by `id()`/string text of different spellings (`n` vs `(n)`); structural only.
- Do not apply to `then_val`/`else_val` with side effects or calls (`_is_flag_preserving_load` is the gate).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_arm64_emission.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py --backend arm64 csinv_ternary
python3 tools/memslot.py --gb 4 --label t -- python3 test_arm64_encoders.py
python3 tools/arm64_insn_audit.py | sed -n 1,25p
```

## Done when
- [ ] csinv emitted for shape 1 (disassembly asserted); answers equal CPython on both backends
- [ ] csinc/csneg emitted for an unsigned/narrow case, or declined with the measured reason in Status
- [ ] signed `+1`/`0-T` keep trapping (test)
- [ ] the new example proves with 0 sorries

## If stuck
If no typed harness can reach shapes 2/3, land shape 1 only and write the exact blocker for 2/3 in Status.
