# plan/step-12a: `len(<string the image holds>)` is a numeral in the proof model; any other string `len` is refused; the post-extern theorem is not emitted for `strlen`
**Status: DONE 2026-11-06 (measured).** Generator side was already in the tree (`_known_string_length`, `str_literal_locals`, `RESULT_BEARING_EXTERNS`, the `NotImplementedError` refusal, FORMAL doc Status); this round found the new `test_len_of_an_image_string_is_its_character_count` had been spliced into the middle of `test_a_returned_string_is_still_run_tested_on_x86_64` (NameError `n`, and that test lost its `subTest` loop) and repaired it: `-k image_string_is` 1 passed (4 subtests, both arches), no `(strlen {` emission outside the generated callFunc arms. `TestGeneratorSource` has 3 pre-existing failures (`_Scope` has no `structs_by_name` at `_call_go`, ~line 933), unrelated and unchanged. Full-file run blocked on the `lib/ProofLib.olean.buildlock` held by another job's Lean rebuild.
Class: mid      Size: M      Depends: 01a, 01b      Blocks: 12b
Source: `bugs/FORMAL_string_value_model.md` bullet "The proving arm64 build cannot prove `len` or any string method" (line ~801) and § "The decision" point 2 (strlen is a computation).

## Current state (measured 2026-11-05; the FORMAL doc bullet is STALE, see below)
- Measured with `compile_formal(path, arch=..., prove=True, check=False)` (no Lean run) on `def main(n: Int) -> Int:\n    var s = "hello"\n    return len(s)`: arm64 AND x86-64 generate a proof that contains `(strlen (UInt64.ofNat 4294969368))` and `MojoExpr.call "strlen" [MojoExpr.var "s"]`. The doc says `len` is "refused at GENERATION time"; that is FALSE on this tree.
- `lib/ProofLib.lean:977-978`: `def strlen : UInt64 → UInt64 := fun _ => 0`. A CONSTANT-ZERO model of strlen. The generator emits it in three places: `_call_go` `formal/arm64_proof_gen.py:708-742`, `_expr_go` `:1625-1649`, `_expr_ast` `:3632-3633` (name normalised to `strlen`); and the generated callFunc arms at `:12501-12508` (`if name = "len" then strlen arg ...`). `ProofLib.lean:1215-1217` evaluates `MojoExpr.call "len"|"strlen"` through the same stub. This violates `doc/finish-formal.md` Global invariant 3 (no fabricated value): model 0 vs machine 5.
- The model/AST sides agree with each other only because BOTH use the stub; the false statements are the machine-vs-model ones. For `len(s)` of an ASCII local the emitter issues `bl strlen` (an extern): `_post_extern_given_callee_returns` is emitted at `formal/arm64_proof_gen.py:12137` guarded by `ret_type_of.get(last["sym"], "int") not in ("none", "")` (line 12109), and its conclusion `... = mojo vals` cannot hold when the program's answer is the callee's own x0 (the doc's analysis).
- x86-64 has no `post_extern_given_callee_returns` (grep: 0 hits in `formal/x86_64_proof_gen.py`); it renders values through the same shared `_expr_go`/`_expr_ast` (its output above contained the same `(strlen ...)`).
- Intern table: `scope.str_addrs` (decoded text -> address), set at `formal/arm64_proof_gen.py:3373-3385, 8439, 8519, 8739, 12853-12872` and `formal/x86_64_proof_gen.py:831-842`; `_str_addr_term(e, scope)` at `:395` renders a literal as `(UInt64.ofNat A)` via `_uint64_lit`.
- The `len` of a LIST blob branch (`return f"(mem_read_u64 (fun _ => 0) {base})"  # placeholder?`, `_call_go`) is ANOTHER fabricated zero. Out of scope here; recorded in Risks of the plan.

## Decisions already made
- The model value of `len(x)` / `strlen(x)` is the NUMERAL `(UInt64.ofNat N)` with `N = len(text)` (Python character count of the decoded literal) exactly when `x`'s text is known to the generator: (a) `x` is a `StringLiteral` expression; or (b) in the `_go` renderers, `x` renders (through `env`) to a term `(UInt64.ofNat A)` whose `A` is a value in `scope.str_addrs` (invert the dict: address -> text; if two texts share an address that is impossible by interning; if `A` is not in the inverse, treat as unknown); or (c) in `_expr_ast`/`_stmts_ast`, `x` is an identifier recorded in the scope's new table `str_literal_locals` (below). Reason: the image's literal bytes are immutable text, so the numeral is true on the machine (ASCII image: `strlen == len`; non-ASCII image: the emitter folds `len` of a literal to the same character count, wave 9).
- Otherwise (a parameter, a call result, a computed string, an unknown address): raise `NotImplementedError("model: len(<name>) of a string whose bytes are not in this image: the model has no memory for it ...")`. NOT `0`. (This is the actual invariant-3 fix; the old stub value is deleted from all three generator sites.)
- `_stmts_ast(stmts, scope)` (`:3918`) maintains `scope.str_literal_locals: dict[name, text]`: on `Assign`/`VarDecl` whose value is a `StringLiteral` set it; on any other assignment to that name delete it; for `IfStmt` process each branch on a COPY and keep only entries equal in both copies (same text); for a `while`/`for` body delete every name assigned inside it before AND after. Add the field to `_Scope.__init__` (`:700-706`) with default `{}`.
- Post-extern suppression is keyed on the callee, not on a new analysis: module-level `RESULT_BEARING_EXTERNS = frozenset({"strlen"})` in `formal/arm64_proof_gen.py`; the guard at `:12109` becomes `... not in ("none","") and last["sym"] not in RESULT_BEARING_EXTERNS`. When suppressed, the surrounding comment block (a docstring above the `if`) says why (the callee's x0 IS the program's answer, so no register-preserved hypothesis can support the conclusion; what remains provable is reachability of the call, which is the `_opaque` halt theorem already emitted). This is the doc's prescription made concrete; the doc's literal phrase "same `_call_boundary` condition" is not usable: `_call_boundary` is only defined, never called in this file (call sites of the family are `_unfollowable_calls` at `:13213, 7893`).
- The generated callFunc arms (`:12501-12508`) keep `strlen arg` text (they are dead for literal-folded programs and unreachable for refused ones); do not edit them.

## Work order
1. `_Scope.__init__`: `self.str_literal_locals: dict = {}`.
2. New helper `_known_string_length(arg, scope, term=None) -> int | None` in `formal/arm64_proof_gen.py` next to `_str_addr_term` (`:395`): implements (a)/(b)/(c); `term` is the already-rendered argument string for the `_go` callers. Returns the int or None.
3. `_call_go` (len branch, `:716-742`), `_expr_go` (`:1625-1649`): replace the three `return f"(strlen {...})"` by: `n = _known_string_length(...)`; `if n is not None: return f"(UInt64.ofNat {n})"`; else `raise NotImplementedError(<message above>)`. Remove the broad `except Exception: return "(strlen ...)"` fallback (it is what keeps the fabricated 0 alive). Keep the blob branch untouched.
4. `_expr_ast` (`:3632`): for `len`/`strlen` of one argument, `n = _known_string_length(e.args[0], scope)`; `n is not None` -> `f"(MojoExpr.int (UInt64.ofNat {n}))"`; else raise the same NotImplementedError. Do not change other calls.
5. `_stmts_ast`: the `str_literal_locals` maintenance above.
6. The suppression guard at `:12109`.
7. Tests in `test_formal_call_proof_gen.py`: add to `STRING_PROGRAMS` (line 105; each is `name: (source, why)`) `len_of_literal_local` (the program above, `N = 5`) and `len_of_literal_direct` (`return len("hi")`; N = 2). In `TestStringValueInTheModel` (line 4432) add `test_len_of_an_image_string_is_its_character_count`: for both arches assert the proof text contains `(UInt64.ofNat 5)` and does not contain `(strlen (UInt64.ofNat` and does not contain `post_extern_given_callee_returns` for the local program (arm64 only for that last assertion). Add to the REFUSED table (line 137, `name: (source, why)`; see how its test asserts a substring) `len_of_a_parameter`: `def f(s: String) -> Int:\n    return len(s)\ndef main(n: Int) -> Int:\n    return f("abc")` with the needle `whose bytes are not in this image`. NOTE the refusal may be raised by a different path first (the callee chain refusal `callee_chain`/`two_args` family); if the needle fails, use a single-function program: `def main(n: Int) -> Int:\n    var s = getenv("HOME")\n    return len(s)` (a string from an extern call).
8. `bugs/FORMAL_string_value_model.md`: correct the stale bullet (line ~801): add a dated Status entry stating the 2026-11-05 measurement (stub zero, not a refusal) and what this step landed.

## Do NOT
- Do not edit `lib/ProofLib.lean` (S4: pinned, expensive). The stub `strlen` stays; step 12b is its design.
- Do not render `len` of an unknown string as the stub; do not fall back to `0`.
- Do not widen `RESULT_BEARING_EXTERNS` beyond `strlen` here (other externs: not measured).
- Do not add a `sorry` in this step.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_call_proof_gen.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_value_model.py
```
(If `test_formal_call_proof_gen.py` runs Lean for some classes it is slow; run it with a single class first: `... test_formal_call_proof_gen.py TestStringValueInTheModel`.)

## Done when
- [ ] the new `TestStringValueInTheModel` test passes on both arches
- [ ] `printf("hi\n")` and `return "small"` tests in the same class still pass
- [ ] `grep -n '(strlen {' formal/arm64_proof_gen.py` shows no remaining emission outside the generated-callFunc text at ~12501
- [ ] the `len(<unknown string>)` program raises NotImplementedError with the new text

## If stuck
If a pre-existing test depends on `(strlen ...)` text (grep `test_*.py` for `strlen`), update it to the numeral only if its subject is `len` of a known string; otherwise stop and write into the doc Status which test, which program, and the proof excerpt.
