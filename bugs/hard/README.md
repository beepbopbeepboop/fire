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
| `CODEGEN_coro_captured_param_capture_crashes.md` | capturing an enclosing function's *parameter* in a nested `async def` raises `ValueError` in the compiler. Increment E widened the capture-plan tuple to 3 elements without widening Increment B's producer to match — **in the same commit that closed the doc claiming Increment B landed.** The feature's own regression file is orphaned at 0/9 and one case asserts the pre-Increment-E answer. **New 2026-09-26.** |
| `CODEGEN_coro_yield_kind_unresolved_callsite.md` | the yield-kind ambiguity gate fires only on *provable* disagreement, so ONE untypable call site silently re-poisons the slot to `int64_t` and discards otherwise-unanimous literal evidence: `g(3.5)` alone is correct, and adding a caller whose argument is a bare identifier makes **both** call sites truncate. `_CALLSITE_PARAM_CONFLICTS`'s own docstring already specifies the fix; it is unimplemented. **New 2026-09-26.** |
| `CODEGEN_function_scoped_import_module_not_inlined.md` | a function-scoped `from X import Y` records Y's signature/exports and then returns without compiling the module: Y's `X.Y(...)` construction returns `0`, and reading a class attribute prints `unavailable in compiled mode` with exit 0. The module-scoped spelling of the same import works. **New 2026-09-26.** |
| `CODEGEN_ctor_arg_field_type_scalars_only.md` | `self.f = param` infers the field type for strings but not lists: `int64_t items` instead of `MojoList *`, so `len`/`[i]` work and `for x in b.items` **segfaults**. A field value round-tripped through a local also loses its type (`t = self.v; return t` prints an address). **New 2026-09-26.** |
| `CODEGEN_method_call_on_struct_param_mistyped.md` | a method call on a struct passed as a free-function *parameter* is mistyped in **every** case — the receiver falls to builtin-container heuristics or `int64_t` — giving SIGBUS, SIGSEGV, or (worst) a plausible wrong value, by method name alone. Root cause: the struct-inference branch requires the receiver to access a *field*, which a method-only receiver never does. **New 2026-09-26.** |
| `CODEGEN_generator_value_slot_loses_bool.md` | a `bool` round-tripping a generator's value slot comes back `1`/`0` instead of `True`/`False`. Silent by construction: the value is a correct 0/1 in a correctly-typed `int64_t`, so every consistency check passes. **New 2026-09-26.** |
| `CODEGEN_same_bare_name_struct_collision_across_modules.md` | two same-named structs in sibling modules collide on an unqualified field table / typedef name. Re-derived 2026-09-26: mechanism intact, but the documented `'Dialog' has no member named 'result'` C error is **gone** (the loser's field access now degrades to dynamic getattr/setattr), and the one genuinely silent residue is a field name **both** structs share — the loser's value is coerced into the winner's ctype, so a `str` field lands as a heap address in an `int64_t` slot. Unfixable *today* only because a **bigger bug sits in front of it**: `module.Class(...)` construction is unresolved on every path, so no program can exhibit this. Fix that first. |
| `CODEGEN_return_type_of_module_constructor_result_erased.md` | a function whose only `return` is a module-level constructor's result (`struct.Struct(...)`) is declared `int64_t`, so every consumer is type-erased and the struct's own attribute reads raise `AttributeError`. The return-value twin of `CODEGEN_method_call_on_struct_param_mistyped.md` (the parameter case). **New 2026-09-26.** |
| `CODEGEN_bytes_silent_wrong_values.md` | six `bytes`/`memoryview` paths that return plausible wrong values with exit 0: `ljust`/`rjust`/`center` with a bytes fill (emits a heap-address byte, so it changes run to run), every empty-bytes predicate `True`, `memoryview.readonly` `False`, and `dict.get`/`dict.pop` reading the str domain for a bytes key. **Two of the repo's own regression tests assert the CPython-wrong answers as expected output**, which is why they survived. **New 2026-09-26.** |
| `CODEGEN_struct_kwargs_and_inline_unpack.md` | `struct.*` keyword arguments are silently DROPPED, not refused — `unpack_from(..., offset=2)` reads offset 0 and returns well-formed wrong data — and the mixed int+float closure only holds for the assigned-to-a-local spelling, so inline `struct.unpack('<if', ...)` still returns the float's raw IEEE-754 bits. **New 2026-09-26.** |

## PARTIAL — the recorded gap is fixed; named residue remains

| doc | what remains |
|---|---|
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
| `CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md` | `CODEGEN_coro_yield_kind_unresolved_callsite.md` |
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

## Notes for future sessions

- **Three test files run in NO suite bucket** — `test_gimple_runner.py` (120
  tests), `test_gimple_generator_runner.py` (145) and
  `test_coro_nested_async_capture.py` (9). No `make check`, no `make gate`
  runs any of them. This is not theoretical: a correct fix sat **red** in
  `test_gimple_runner.py` for a full pass because nothing ran it, and the
  coro file is 0/9 partly because its source list still names pre-rename
  `mojo_*` runtime files (now `fire_*`). Registering those three is the
  highest-value structural fix available in this directory — bigger than any
  single bug listed above it.
- **Two of the OPEN entries were found by re-testing claims in an existing
  doc rather than by reading code.** The `.format` residual had been
  recorded as "returns a pointer-sized integer ... and a local is correct
  too"; on re-test both halves were wrong. Stale bug docs are not evidence.
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
