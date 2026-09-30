# bugs/hard — triage index

The hard-bug set. "Hard" here means one of two things, both of which make a
bug expensive to leave lying around:

- a **silent miscompile** — wrong value or garbage, exit 0, no diagnostic;
- a **compile refusal** on a shape real stdlib code actually uses.

Every entry carries a `**State: CLOSED | PARTIAL | OPEN.**` banner directly
under its title, with the residue named. Start there; the banner tells you
whether re-reading the body is worth your time.

Last updated 2026-09-29.

## OPEN — not fixed, no code change yet

| doc | one line |
|---|---|
| `CODEGEN_same_bare_name_struct_collision_across_modules.md` | two same-named structs in sibling modules collide on an unqualified field table / typedef name. Re-derived 2026-09-26: mechanism intact, but the documented `'Dialog' has no member named 'result'` C error is **gone** (the loser's field access now degrades to dynamic getattr/setattr), and the one genuinely silent residue is a field name **both** structs share — the loser's value is coerced into the winner's ctype, so a `str` field lands as a heap address in an `int64_t` slot. Unfixable *today* only because a **bigger bug sits in front of it**: `module.Class(...)` construction is unresolved on every path, so no program can exhibit this. Fix that first. |

## PARTIAL — the recorded gap is fixed; named residue remains

| doc | what remains |
|---|---|
| `CODEGEN_coro_captured_param_capture_crashes.md` | capturing an enclosing function's *parameter* in a nested `async def` raised `ValueError` in the compiler. **FIXED 2026-09-26** — and not with the doc's one-liner: the capture plan is now a named `_Capture` class with one constructor, because the positional 3-tuple that three passes unpacked blindly is what caused the crash. Items 2/3 remain: a cross-closure `async for` neighbour shape that is neither refused nor correct, and a nested async generator driven by `async for` in its own enclosing function. |
| `CODEGEN_coro_yield_kind_unresolved_callsite.md` | one untypable call site silently re-poisoned the yield slot to `int64_t`. **FIXED 2026-09-26** for cases 1–7, and *correct* rather than refused — the evidence was always reachable, it just was not read. The doc's own docstring parenthetical is implemented, plus six sound widenings (any-annotation is not a hole; a bare identifier bound to a list answers `('list', k)`; `if caller_env:` was truthiness where membership was meant; ordinary `def`s are now scanned too). One shape has no reachable evidence and must stay refused. Case 8 reclassified: it is the ordinary loop lowering, not this subsystem. |
| `CODEGEN_method_call_on_struct_param_mistyped.md` | a method call on a struct passed as a free-function *parameter* was mistyped by method name alone — 6 crashes plus 2 silent wrong values. **FIXED 2026-09-26** for everything it owns: 8/8 names now correct, via a new cross-call contract in Pass 1.3d plus three supporting fixes. The doc's suggested refusal was not needed; the call site knows the type. One cross-module row remains and is *not* this bug in link mode — `module.Class(...)` construction is unresolved on every path, the larger gap named above. |
| `CODEGEN_bytes_silent_wrong_values.md` | six `bytes`/`memoryview` paths returning plausible wrong values with exit 0. **5 of 6 FIXED 2026-09-26**, plus several found alongside: a bytes fill char that emitted a heap-address byte, empty-bytes predicates, `memoryview.readonly`, `dict.get`/`pop` on a bytes key, a loop-target rebind that was never bytes-specific, and swapped `partition` arms, a non-raising empty separator, `center` padding on the wrong side and a `width` keyword read as the fill. `isprintable`/`isnumeric` were **removed from `bytes`** (CPython raises; only the buggy code dissented) and added to `str`, where they answered a silent `0`. Two enshrined-wrong test expectations were corrected. Residue: `partition` returns a `MojoList *` because **this runtime has no tuple type at all** — not a bytes fix. |
| `CODEGEN_struct_kwargs_and_inline_unpack.md` | `struct.*` keyword arguments were silently dropped, and mixed int+float `unpack` returned raw IEEE-754 bits. **BOTH FIXED 2026-09-26**, and the residue under the second one **FIXED 2026-09-29**: the per-slot kinds now travel with the VALUE (a side table on the live `MojoList` address, `mojo_list_set_kinds`) instead of dying with one compile-time C name, so a copy, a slice, a concat, a returned value and a class attribute's `Struct` handle all read back correctly; and a read with no compile-time slot index — iteration, a computed subscript — is **boxed** (`mojo_list_get_boxed` + `mojo_repr_boxed`), which also fixes the heterogeneous `[1, 2.5]` literal that the doc named as the root cause underneath it. A uniform format records nothing and pays nothing. One thing the work uncovered is a DIFFERENT bug and is filed separately: a function returning a `MojoList *` it built in a local is typed `int64_t`, so the caller print()s the address and iterating it segfaults (pre-existing, not `struct`). |
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
| `CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md` | `CODEGEN_function_scoped_import_module_not_inlined.md` — itself since fixed and deleted; see the 2026-09-29 section below |
| `CODEGEN_unannotated_init_param_field_type_defaults_int64.md` | `CODEGEN_ctor_arg_field_type_scalars_only.md` |
| `CODEGEN_generator_consuming_generator_value_ctype.md` | `CODEGEN_generator_value_slot_loses_bool.md` |

Nothing is left on the "still to verify" list. A ninth CLOSED report's
analysis (`CODEGEN_same_bare_name_struct_collision_across_modules.md`) was
re-derived and kept — see its OPEN row for the three load-bearing claims that
turned out to be false.

### 2026-09-29: one removal with no residue of its own — and what that cost

`CODEGEN_function_scoped_import_module_not_inlined.md` (the OPEN row it came
from, opened 2026-09-26, its own banner "link-mode still OPEN") is **fixed
and deleted**. All five of its rows now match CPython on BOTH pipelines —
measured, 11/11 shapes including a no-import control, and including the
`enum.py.__signature__` three-class repro that is the original bug's exact
territory. So this is the first removal here that did **not** follow the
8-for-8 pattern above, and the reason is worth recording rather than
letting the pattern look inviolable: the 2026-09-26 pass closed it on a
narrower **spelling** (the single-TU path, cause (c) above), and the
2026-09-29 pass closed it on the other pipeline. The residue it DID turn up
belongs to other bugs, not to this one, so it is filed in `bugs/`, not here:

| found while fixing it | filed as |
|---|---|
| `linkmode` was **already red on master** — a `from . import SUB` + `SUB.f(...)` call prints 0, exit 0 | `bugs/CODEGEN_link_mode_bare_submodule_marker_call_silent_wrong_value.md` |
| a `from p import f` whose module only RE-EXPORTS `f` names the re-exporting module, not the defining one | `bugs/CODEGEN_reexported_function_import_qualifier_names_the_wrong_module.md` |
| `import p.sub` + `p.sub.f(14)` exits 1 with no output, on both pipelines | `bugs/CODEGEN_import_dotted_name_two_hop_attribute_call_exits_1.md` |
| an enclosing function's return type is `int64_t` when its only `return` is a method call, so a `char *` prints as a pointer decimal | `bugs/CODEGEN_return_type_not_inferred_from_a_method_call_result.md` |
| `str()`/`%s` never consult `__str__`; a struct inside a list/tuple reprs as a raw pointer | `bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md` |

The first of those is the one to act on first: while `linkmode` is red it
cannot be used to distinguish a new regression from a pre-existing failure,
and the doc it came from had explicitly warned that a change in this area
"owes the full gate plus manual re-triage of the `COMPILE_FAIL_*.md`
corpus" — which is exactly what turned it up.

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

- **CORRECTED 2026-09-29: those three test files are registered now.** This
  paragraph used to say `test_gimple_runner.py`, `test_gimple_generator_runner.py`
  and `test_coro_nested_async_capture.py` run in no suite bucket, and it was
  the highest-value structural fix available in this directory. `tools/suite.py`
  registers the first two as `gimplerunner` and `gimplegenerators`, both in
  `check` (`python3 tools/suite.py --list` is the authority), and
  `test_suite.py`'s own estate walk now reports 83 test files, 52 registered
  and 33 each with a written reason — 0 undeclared. Kept as a paragraph
  because "no bucket" was the single most expensive rot in this file's
  history: the same `test_gimple_runner.py` that once hid a correct fix red
  for a full pass is what caught this branch's regression tests, and what
  reported 176/176 after every change to it.
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
