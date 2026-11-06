# plan/step-24: x86-64 arch drift is mostly ALREADY CLOSED: pin it and correct the doc
**Status: DONE 2026-11-05 (verified).** x86-64 parity suite PASS=90 FAIL=0 (unary `^` case `ownership_transfer_caret` included); `refuse_either:does not fold` no longer appears in `test_formal_run.py`; `FORMAL_known_limits.md` §6.5 reads CLOSED.

Class: easy      Size: S      Depends: none      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.5 (stale) and §3 table row "`comptime X = … does not fold`" (already says CLOSED 2026-09-27)

## Current state (measured; file:line verified 2026-11-05)
- P0: `python3 -c "import formal.model"` must succeed. At HEAD it fails (`NameError: threading`, `formal/model/layout.py:3155`). If still broken, add `import threading` at the top of `formal/model/layout.py` as its own first commit.
- Item 1, unary `^` on x86-64: FIXED in the tree. `formal/x86_64_codegen.py:9511-9525` has the `M.is_ownership_transfer(expr)` branch (the comment there says it is the `swap.mojo` fix). Pinned by `test_formal_x86_64_parity.py` case `ownership_transfer_caret` (line ~810, with a negative-value twin right after). §6.5 still says "arm64 builds it, x86-64 refuses it": stale.
- Item 2, comptime over a subscript: the `SubscriptExpr` refusal text `unsupported call target ... (got SubscriptExpr)` still exists at `x86_64_codegen.py:13063` but is only the LAST fallthrough; the comptime path is shared: `x86_64_codegen.py:2826` (`ComptimeVarStmt` arm) and :2937 call `M.comptime_fold_refusal(name)` exactly as `arm64_codegen.py:14377` does. `test_formal_x86_64_parity.py:2102` `comptime_binding_initialized_by_a_call` pins the shared hook.
- The one remaining LOOSE pin: `test_formal_run.py:2153` `limit_comptime_over_a_runtime_parameter` is `refuse_either:does not fold to a compile-time constant|unsupported statement ComptimeVarStmt`. Its comment (:2139-2146) says x86-64 has "no comptime statement lowering at all" — false now (x86 has the :2826 arm). `refuse_either` hides exactly the drift this step is about.
- UNVERIFIED — worker must check first: whether x86-64 now says `does not fold to a compile-time constant` for that program. Command: write the 5-line program from :2154-2158 to a temp `.mojo`/`.py` file and run `python3 fire.py build --formal --no-prove --backend=x86_64 <file>` and with `--backend=arm64` (look at how `test_formal_run.py` invokes a case; run it by name: `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py limit_comptime_over_a_runtime_parameter`).

## Decisions already made
- NO codegen change in this step. If the measurement above shows x86-64 still refuses with a different text, that is a bug to FIX in `x86_64_codegen.py` by routing to `M.comptime_fold_refusal` (same call as :2937) — that is then this step's code change, and must not touch arm64.
- Tighten, do not delete, the pin: change `refuse_either:` to `refuse:` with the single needle `does not fold to a compile-time constant` (the `refuse:` form asserts the shared text on both backends; see the comment at test_formal_run.py:2128-2131).

## Work order
1. P0. Then measure both backends for `std/math/polynomial.mojo` and `std/builtin/swap.mojo` (stdlib at `$MOJO_STDLIB`, found by `module_loader.STDLIB_PATH`; e.g. `/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std/math/polynomial.mojo`): `python3 tools/memslot.py --gb 8 --label t -- python3 tools/formal_sweep.py --no-stdlib --arch arm64 <file>` is NOT right for a stdlib file; use `python3 tools/formal_sweep.py --stdlib <stdlib root> --stdlib-subtrees std/math -j 1 --arch arm64` then `--arch x86_64` and compare the two verdict lines for the two files (check `--help` for the exact spelling; keep it to the two files' subtrees).
2. If both files are in the same class with the same message (swap: builds on both; polynomial: `comptime ... does not fold`) go to 3; else fix per Decisions.
3. `test_formal_run.py:2139-2159`: change the row's kind to `refuse:` + the single needle; rewrite the comment to say x86-64 now shares `comptime_fold_refusal`.
4. `bugs/FORMAL_known_limits.md` §6.5: replace the body with a dated "CLOSED 2026-11-05" paragraph naming `ownership_transfer_caret` and the tightened row; fix the §3 row's last clause accordingly. §6.5 title "still open, still two files" must change.
5. `python3 tools/dangling_doc_refs.py --ratchet` and compare with pre-step output (S5).

## Do NOT
- Do not touch arm64.
- Do not delete `FORMAL_known_limits.md` (other sections are open).
- Do not leave `refuse_either` for a row where both backends now agree.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_x86_64_parity.py ownership_transfer_caret comptime_binding_initialized_by_a_call
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py limit_comptime_over_a_runtime_parameter
```

## Done when
- [ ] both commands pass; the run row uses `refuse:` (grep `refuse_either:does not fold` in test_formal_run.py returns nothing)
- [ ] §6.5 says CLOSED with the date; the two files measured in the same class on both architectures (paste the two verdict lines into the Status)

## If stuck
If x86-64 still refuses `polynomial.mojo` with a different text and the routing change breaks other x86 rows, write the diverging messages into §6.5 Status and stop.
