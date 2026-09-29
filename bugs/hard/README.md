# bugs/hard — triage index

The hard-bug set. "Hard" here means one of two things, both of which make a
bug expensive to leave lying around:

- a **silent miscompile** — wrong value or garbage, exit 0, no diagnostic;
- a **compile refusal** on a shape real stdlib code actually uses.

Every entry carries a `**State: CLOSED | PARTIAL | OPEN.**` banner directly
under its title, with the residue named. Start there; the banner tells you
whether re-reading the body is worth your time.

Last updated 2026-09-26.

## OPEN — not fixed, no code change yet

| doc | one line |
|---|---|
| `CODEGEN_function_scoped_import_module_not_inlined.md` | a function-scoped `from X import Y` records Y's signature/exports and then returns without compiling the module: Y's `X.Y(...)` construction returns `0`, and reading a class attribute prints `unavailable in compiled mode` with exit 0. The module-scoped spelling of the same import works. **New 2026-09-26.** |
| `CODEGEN_same_bare_name_struct_collision_across_modules.md` | two same-named structs in sibling modules collide on an unqualified field table / typedef name. Re-derived 2026-09-26: mechanism intact, but the documented `'Dialog' has no member named 'result'` C error is **gone** (the loser's field access now degrades to dynamic getattr/setattr), and the one genuinely silent residue is a field name **both** structs share — the loser's value is coerced into the winner's ctype, so a `str` field lands as a heap address in an `int64_t` slot. Unfixable *today* only because a **bigger bug sits in front of it**: `module.Class(...)` construction is unresolved on every path, so no program can exhibit this. Fix that first. |

## PARTIAL — the recorded gap is fixed; named residue remains

| doc | what remains |
|---|---|
| `CODEGEN_coro_captured_param_capture_crashes.md` | capturing an enclosing function's *parameter* in a nested `async def` raised `ValueError` in the compiler. **FIXED 2026-09-26** — and not with the doc's one-liner: the capture plan is now a named `_Capture` class with one constructor, because the positional 3-tuple that three passes unpacked blindly is what caused the crash. Items 2/3 remain: a cross-closure `async for` neighbour shape that is neither refused nor correct, and a nested async generator driven by `async for` in its own enclosing function. |
| `CODEGEN_method_call_on_struct_param_mistyped.md` | a method call on a struct passed as a free-function *parameter* was mistyped by method name alone — 6 crashes plus 2 silent wrong values. **FIXED 2026-09-26** for everything it owns: 8/8 names now correct, via a new cross-call contract in Pass 1.3d plus three supporting fixes. The doc's suggested refusal was not needed; the call site knows the type. One cross-module row remains and is *not* this bug in link mode — `module.Class(...)` construction is unresolved on every path, the larger gap named above. |
| `CODEGEN_bytes_silent_wrong_values.md` | six `bytes`/`memoryview` paths returning plausible wrong values with exit 0. **5 of 6 FIXED 2026-09-26**, plus several found alongside: a bytes fill char that emitted a heap-address byte, empty-bytes predicates, `memoryview.readonly`, `dict.get`/`pop` on a bytes key, a loop-target rebind that was never bytes-specific, and swapped `partition` arms, a non-raising empty separator, `center` padding on the wrong side and a `width` keyword read as the fill. `isprintable`/`isnumeric` were **removed from `bytes`** (CPython raises; only the buggy code dissented) and added to `str`, where they answered a silent `0`. Two enshrined-wrong test expectations were corrected. Residue: `partition` returns a `MojoList *` because **this runtime has no tuple type at all** — not a bytes fix. |
| `CODEGEN_struct_kwargs_and_inline_unpack.md` | `struct.*` keyword arguments were silently dropped, and mixed int+float `unpack` returned raw IEEE-754 bits. **BOTH FIXED 2026-09-26.** Keywords are *honoured* rather than refused, bounded to the three names CPython actually accepts (measured by brute force over the real module), including its error-message precedence. The doc's mechanism for the unpack half was wrong: it is not about locals — of six consuming spellings exactly one worked, and the literal-index subscript was the survivor. Residue: a read with no compile-time slot index still needs one C type for a heterogeneous value, which is the runtime's missing container tag. |
| `CODEGEN_generator_lambda_expr_unsupported.md` | **rewritten 2026-09-26: the recorded residue was stale.** Escaping/rebound capturing lambdas are CLOSED — they take a heap env, and the escape analysis now only picks between two correct lowerings. What remains is the **variadic** shape, and it is a call-site SIGSEGV rather than a lost capture: the lifted definition is correct (`int64_t f (MojoList * a)`) but the call site passes loose args positionally as scalars and never packs the list, so the callee dereferences address 4. Three corpus sites. Still excluded: capturing lambdas inside a coroutine body. |
| `COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` | **corrected 2026-09-26: both of the doc's conclusions were wrong.** The real file is on disk, and rebuilding the audit against it (every earlier reconstruction had dropped the kw-only callable-parameter indirection) shows **4 of the 6 shapes the doc called "WORKS" are still refused**. The real blocker is *invoking a kw-only param as a callee*, the same missing callable-value representation the lambda doc names, from a different direction. Its shape-5 mapping is RETRACTED: that shape is refused outright, so it never witnessed the `value_ctype` bug at all. |

## Closed reports are deleted, not kept as monuments

A doc for a bug that is fully fixed is **removed**, per CLAUDE.md's "Bug
docs" rule. There is deliberately no CLOSED section listing them: a fixed bug
still listed is indistinguishable from an open one, and the "re-verified
unchanged" entries that accumulate in a long-lived doc cost the next session
real time to re-derive and change nothing.

An earlier version of this file said the opposite — that closed docs must be
kept because they record *mechanisms* that are easy to reintroduce. That was
a reasonable argument and it was wrong, for a reason the verification pass
made concrete: on 2026-09-26 two closed reports were re-tested and **both
still had live, silent, wrong-value residue** that their own text did not
have. Keeping the file did not prevent that; it hid it, behind a CLOSED
banner that everyone had stopped reading. The residue is now two new OPEN
docs above (`CODEGEN_bytes_silent_wrong_values.md`,
`CODEGEN_struct_kwargs_and_inline_unpack.md`), which is the honest home for
it. Mechanistic knowledge that still matters lives in the source comment
that explains the mechanism, not in a doc about a bug that no longer exists.

Verified-closed and removed on 2026-09-26 — eight reports. **Every single
one still had live residue when re-tested**, so each removal also produced a
new OPEN doc above rather than losing the residue:

| removed | residue now tracked in |
|---|---|
| `CODEGEN_bytes_value_type.md` | `CODEGEN_bytes_silent_wrong_values.md` |
| `CODEGEN_struct_module.md` | `CODEGEN_struct_kwargs_and_inline_unpack.md` |
| `CODEGEN_struct_format_shadowed_by_format_attribute.md` | `CODEGEN_return_type_of_module_constructor_result_erased.md` |
| `CODEGEN_coro_nested_async_closure_capture.md` | `CODEGEN_coro_captured_param_capture_crashes.md` |
| `CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md` | `CODEGEN_coro_yield_kind_unresolved_callsite.md`, itself removed 2026-09-29; its residue is now in `../CODEGEN_generator_param_loop_target_kinds_still_unresolved.md` |
| `CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md` | `CODEGEN_function_scoped_import_module_not_inlined.md` |
| `CODEGEN_unannotated_init_param_field_type_defaults_int64.md` | `CODEGEN_ctor_arg_field_type_scalars_only.md` |
| `CODEGEN_generator_consuming_generator_value_ctype.md` | `CODEGEN_generator_value_slot_loses_bool.md` |

Nothing is left on the "still to verify" list. A ninth CLOSED report's
analysis (`CODEGEN_same_bare_name_struct_collision_across_modules.md`) was
re-derived and kept — see its OPEN row for the three load-bearing claims that
turned out to be false.

**The rate matters more than the count.** 8-for-8 is not a coincidence, and
it is not a reason to trust the next CLOSED banner either. The recurring
causes, all found repeatedly on 2026-09-26: (a) a regression test asserting
the CPython-wrong answer, so the suite actively protects the bug; (b) a
regression test file in no `tools/suite.py` bucket, so nothing runs it; and
(c) a doc closed on a narrower *spelling* than the one still broken.

`PERF_nested_module_compile_walk_ast_quadratic_rescan.md` is **not** in that
list despite still being listed here historically: the AST-node rescan it is
named for is genuinely fixed and linear, but a fresh 2026-09-26 measurement
found the remaining per-level rescan over generated C text is still
superlinear (`_dedup_variadic_externs`, halved and cached in Phase 7 but
still ~n^1.7), so the doc stays OPEN.

### A ninth removal, and what it cost (2026-09-29)

`CODEGEN_coro_yield_kind_unresolved_callsite.md` is the first doc in this
directory removed under the rule above since the 2026-09-26 sweep, and it
behaves the way that rule predicts: re-testing its own claims turned up **two
load-bearing ones that were false**, and both changed what got fixed.

- It said the `print(x)` half of its "test hole" was the cross-cutting
  one-C-type-per-slot limitation, "an ordinary `def g(x): return x` does the
  same". Re-measured, the ordinary case does **not** (it is correct), and the
  real shape SEGFAULTS with a **single** call site — because
  `'print': 'char *'` types the parameter from the one observation available.
  Cause (c) again, in a new costume: the doc had been closed on a *different
  subsystem's* limitation, so the shape it pointed at was never its own bug.
  Now `../CODEGEN_print_unannotated_param_typed_char_star_segfaults.md`.
- It said item 8 belonged to "a different subsystem ... Not attempted here".
  The subsystem was reachable and the contract it named already existed; it
  was fed from one observation source instead of two. Closed, both halves,
  with three more regression docs: `../CODEGEN_generator_param_loop_target_
  kinds_still_unresolved.md`, `../CODEGEN_nested_list_loop_target_loses_inner_
  elem_type.md`, and the `print` one above.

## Notes for future sessions

- **The three unrun test files are now registered** (corrected 2026-09-29;
  the note below was written 2026-09-26 and is kept because the *reason* it
  matters has not changed). `test_gimple_runner.py` is `gimplerunner`,
  `test_gimple_generator_runner.py` is `gimplegenerators` (both in `check`
  and `gate`), and `test_coro_nested_async_capture.py` is
  `coro-nested-capture` (in `gate`/`coroutine`, and its pre-rename
  `mojo_*`-runtime source list is fixed). The history is still worth reading:
  a correct fix sat **red** in `test_gimple_runner.py` for a full pass
  because nothing ran it, which is what made the structural fix worth doing.
  A fourth file remains in no bucket — `test_gimple_async_runner.py` is
  registered as `gimple-async-runner` but carries `expect=` (36 failing), so
  it runs and its result is not yet evidence of anything.
  single bug listed above it.
- **Two of the OPEN entries were found by re-testing claims in an existing
  doc rather than by reading code.** The `.format` residual had been
  recorded as "returns a pointer-sized integer ... and a local is correct
  too"; on re-test both halves were wrong. Stale bug docs are not evidence.
  The 2026-09-29 removal above is the same lesson a third time, and the sharpest
  instance yet: the doc's own *test hole* named a shape it then declined to fix
  on the grounds that it belonged to a limitation that turned out not to apply
  to it at all. Re-measuring the claim would have found a **segfault**.
- **That `.format` entry is now closed and its doc deleted** (2026-09-26). The
  fix closed the `struct.Struct` member-call branch for the whole closed type,
  not just the one name: `s.format(x)` and `s.size()` now raise the CPython
  `TypeError` instead of a silent `0` / a phantom-symbol link failure, and any
  other name is the CPython `AttributeError`. Chasing its residue is what
  produced `CODEGEN_return_type_of_module_constructor_result_erased.md`, which
  is a *distinct* bug (it breaks the attribute read too) and is the reason that
  doc was deleted rather than kept.
- `BUGFIX_ROADMAP.md` in the parent directory tracks the wider
  (non-hard) set.

## Known rot in these docs: 9 dangling cross-references

While adding the state banners I checked every `*.md` filename mentioned
inside these docs. Nine resolve to nothing — the target file does not exist
anywhere in the repo, so they were deleted or renamed at some point and the
references were never updated:

| missing target | referenced from |
|---|---|
| `CODEGEN_args_kwargs_signature_assumed_forwarding_only.md` | `CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md`, `CODEGEN_generator_lambda_expr_unsupported.md` |
| `CODEGEN_coro_stackswitch_body_semantics_gaps.md` | `CODEGEN_generator_lambda_expr_unsupported.md` |
| `CODEGEN_function_scoped_import_call_unresolved_at_link.md` | `CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md` |
| `CODEGEN_generator_non_plain_assignment_target_refused.md` | `CODEGEN_generator_lambda_expr_unsupported.md` |
| `CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md` | `COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` |
| `CODEGEN_generator_struct_typed_param_refused.md` | `CODEGEN_generator_lambda_expr_unsupported.md` |
| `COMPILE_FAIL_importlib__bootstrap.md` | `CODEGEN_unannotated_init_param_field_type_defaults_int64.md` |
| `COMPILE_FAIL_tkinter_filedialog.md` | `CODEGEN_same_bare_name_struct_collision_across_modules.md` |
| `COMPILE_FAIL_Tools_cases_generator_cwriter.md` | `CODEGEN_unannotated_init_param_field_type_defaults_int64.md` |

Deliberately **not** guessed at. Each of these was presumably a real bug
doc, so the fix is to recover the content from history (`git log
--diff-filter=D --name-only -- 'bugs/*'`) and either restore the file or
fold its content into whichever doc now cites it — not to invent a
replacement link, which would hide the loss. Flagged rather than fixed
because it needs a history spelunking pass, not a text edit.
