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
| `CODEGEN_generator_consuming_generator_value_ctype.md` | a generator consuming a sibling generator types the yielded value `int64_t` instead of the callee's real `value_ctype`. Silent, and it compounds along a consumption chain. Root-caused to `lower()` running before `register()`; needs a fixpoint, and the existing retry is structurally blind to it (the consumer never raises). **New 2026-09-26.** |
| `CODEGEN_struct_format_shadowed_by_format_attribute.md` | `Struct.format(x)` returns `0` where CPython *and this repo's own reference interpreter* both raise `TypeError`. Pre-existing (confirmed on a clean `HEAD~1`). The attribute *read* is correct — only the call is wrong. **New 2026-09-26.** |
| `CODEGEN_same_bare_name_struct_collision_across_modules.md` | two same-named structs in sibling modules collide on an unqualified field table / typedef name. Deprioritised since 2026-08-09, untouched since. |

## PARTIAL — the recorded gap is fixed; named residue remains

| doc | what remains |
|---|---|
| `CODEGEN_generator_lambda_expr_unsupported.md` | variadic (`*args`/`**kwargs`) captures, and capturing lambdas that **escape** or are rebound — both still lose their captures. These need the env-struct / callable-value representation that nested `def` closures already use. Also deliberately excluded: capturing lambdas inside a coroutine body (that body model is scalar-only). |
| `COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` | 5 of its 6 recorded shapes are already fixed upstream. The 6th is not fsutil-specific — it is the `value_ctype` bug above, which this doc now only points at. |

## CLOSED — verified landed

`CODEGEN_bytes_value_type.md` ·
`CODEGEN_coro_nested_async_closure_capture.md` ·
`CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md` ·
`CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md` ·
`CODEGEN_struct_module.md` ·
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md` ·
`PERF_nested_module_compile_walk_ast_quadratic_rescan.md`

## Notes for future sessions

- **"CLOSED" does not mean the file can be deleted.** These record
  *mechanisms* — a wrong pass, a missing scan, a bad type default — that are
  easy to reintroduce, and each status entry says which. Several closed here
  by turning a silent miscompile into an honest refusal rather than by
  implementing the shape; that trade is deliberate and documented per entry.
- **Two of the OPEN entries were found by re-testing claims in an existing
  doc rather than by reading code.** The `.format` residual had been
  recorded as "returns a pointer-sized integer ... and a local is correct
  too"; on re-test both halves were wrong. Stale bug docs are not evidence.
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
