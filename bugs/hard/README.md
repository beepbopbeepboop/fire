# bugs/hard — triage index

The hard-bug set. "Hard" here means one of two things, both of which make a
bug expensive to leave lying around:

- a **silent miscompile** — wrong value or garbage, exit 0, no diagnostic;
- a **compile refusal** on a shape real stdlib code actually uses.

Every entry carries a `**State: CLOSED | PARTIAL | OPEN.**` banner directly
under its title, with the residue named. Start there; the banner tells you
whether re-reading the body is worth your time.

Last updated 2026-10-01.

## OPEN — not fixed, no code change yet

| doc | one line |
|---|---|
| `CODEGEN_function_scoped_import_module_not_inlined.md` | a function-scoped `from X import Y` records Y's signature/exports and then returns without compiling the module: Y's `X.Y(...)` construction returns `0`, and reading a class attribute prints `unavailable in compiled mode` with exit 0. The module-scoped spelling of the same import works. **New 2026-09-26.** |

## PARTIAL — the recorded gap is fixed; named residue remains

| doc | what remains |
|---|---|
| `CODEGEN_method_call_on_struct_param_mistyped.md` | a method call on a struct passed as a free-function *parameter* was mistyped by method name alone — 6 crashes plus 2 silent wrong values. **FIXED 2026-09-26** for everything it owns: 8/8 names now correct, via a new cross-call contract in Pass 1.3d plus three supporting fixes. The doc's suggested refusal was not needed; the call site knows the type. One cross-module row remains and is *not* this bug in link mode — `module.Class(...)` construction is unresolved on every path, the larger gap named above. |
| `COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` | **the kw-only-callable blocker is FIXED for the same-module case, 2026-09-29.** `walk_tree` and `iter_files_by_suffix` now compile and produce CPython's text; the stack-switch `kwonly params (v0)` gate is a representability question instead of a blanket refusal, and a callable-valued parameter's default is a real function address instead of a NULL pointer (which used to SIGSEGV on **every** path, ordinary `def`s included — that half was not in the doc). Residue: `_walk_tree`/`glob_tree` still refuse because their defaults name an **imported** module's function, undecidable at A3's eligibility time, and that same gap is a live SIGSEGV on the ordinary path (`bugs/CODEGEN_unresolved_imported_callable_default_null_pointer.md`); `iter_files`'s variadic lambda and `process_filenames`' `Exception(...)`-as-a-value are separate and outside this bug, so the file still does not build. |

### 2026-10-02: two more rows closed, and the third one's *diagnosis* replaced with its two real causes

`CODEGEN_cross_module_struct_ctor_at_module_scope_mistyped.md` (OPEN, the
2026-09-30 row) and `CODEGEN_cross_function_container_element_type.md` are
**fixed and deleted**. Both were diagnosed as a scope or an identity problem
and were neither; in both cases the real cause is a set of CALL SITES a pass
never collected, which is a much smaller and much more checkable defect than
either doc's "exact next step" section claimed to need.

The module-scope one: the cross-module constructor field-type hint pre-pass
collects its sites by walking `FunctionDef` bodies only, so a module-level
`insp.Parameter('v', 7)` was in no collected set. Not the import seam (both
spellings were equally wrong, and both were right inside a function) and not
module scope alone (the same-file case is correct at module scope, because in
one translation unit the struct's own field table is registered before the
module's statements are emitted). One line: extend the site collector.

The container-element one is two independent halves of the same pass, and
naming them separately is the transferable part. `gen._elem_types` is a
per-function map keyed by lowered C value, which is why a container shared
across functions loses its element type — but the pass that is supposed to
conclude otherwise (`_gmi_phase17_collect_appends`, keyed on a module GLOBAL's
name and so function-independent by construction) had two gaps of its own: it
walked `FunctionDef`/`If`/`While`/`For`/`Try`/`With` but **not `StructDef`**, so
an append inside a constructor — the dominant registry shape — was invisible
to the whole pass; and its receiver test required a bare `IdentExpr`, so the
class-attribute spelling `T.registry.append(self)` was rejected as well. The
doc's own fix sketch — a `_value_sources` provenance chain through
`_coerce_to_type` — is not needed for either, because the pass that already
exists for exactly this question was simply not being asked.

Both fixes are worth reading together with the two rows above them: three of
the five instances of cause (c) in this file were "one spelling of a working
site collection was never wired up", and in every case the cheap check was to
write both spellings of the same program down side by side and diff.

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
banner that everyone had stopped reading. The residue became new OPEN docs
(`CODEGEN_bytes_silent_wrong_values.md` and what was then
`CODEGEN_struct_kwargs_and_inline_unpack.md`), which was the honest home for
it. **Both of those are themselves gone now** — closed and deleted, the
`struct` one on 2026-10-02 — which is the arc the next paragraph describes,
run to its end. Mechanistic knowledge that still matters lives in the source comment
that explains the mechanism, not in a doc about a bug that no longer exists.

**The bytes doc followed the same arc, one round further, and is now gone
too.** `CODEGEN_bytes_silent_wrong_values.md` sat in the PARTIAL table below
with a single named residue — `partition`'s container TYPE — and the reason
it gave for not fixing it was that "this runtime has no tuple type at all,
which is a change to every container lowering in the backend". Re-tested on
2026-09-29, that premise was **false**: a tuple type has existed for some
time as the `mojo_mark_as_tuple` marker, used at eight construction sites
and already read by `isinstance(x, tuple)`. The marker was simply not
*load-bearing* — read by `repr` and nothing else — so a tuple was a list that
printed like one. Making the marker load-bearing closed the residue and,
while in the same helper family, turned up two more silent wrong values the
doc had not: `l == m` was a raw C **pointer** comparison (identity, not
value) and `list.count(x)` had no lowering at all and answered 0. A
differential sweep of the bytes/memoryview/`str` surface then found twelve
more, plus a bytes-literal decoder missing `\a`, `\b`, `\f` and `\v`. The
doc is removed, per this file's own rule.

This is the second time a residue's stated reason for existing was stale
rather than the residue itself, which is worth more than the two bugs: it
means **a doc's explanation of why it is still open deserves the same
suspicion as its explanation of what is broken.**

Verified-closed and removed on 2026-09-26 — eight reports. **Every single
one still had live residue when re-tested**, so each removal also produced a
new OPEN doc above rather than losing the residue:

| removed | residue now tracked in |
|---|---|
| `CODEGEN_bytes_value_type.md` | (both now closed and removed) |
| `CODEGEN_struct_module.md` | `CODEGEN_struct_kwargs_and_inline_unpack.md` (itself closed and deleted 2026-10-02) |
| `CODEGEN_struct_format_shadowed_by_format_attribute.md` | `CODEGEN_return_type_of_module_constructor_result_erased.md` |
| `CODEGEN_coro_nested_async_closure_capture.md` | `CODEGEN_coro_captured_param_capture_crashes.md` — itself closed and removed 2026-09-29 |
| `CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md` | `CODEGEN_coro_yield_kind_unresolved_callsite.md` — itself **fixed and removed 2026-10-01** by `work/hard-coro-yield`; its residue is now in `../CODEGEN_generator_param_loop_target_kinds_still_unresolved.md` |
| `CODEGEN_function_scoped_import_rettype_and_literal_cast_mismatches.md` | `CODEGEN_function_scoped_import_module_not_inlined.md` — itself since fixed and deleted; see the 2026-09-29 section below |
| `CODEGEN_unannotated_init_param_field_type_defaults_int64.md` | `CODEGEN_ctor_arg_field_type_scalars_only.md` |
| `CODEGEN_generator_consuming_generator_value_ctype.md` | `CODEGEN_generator_value_slot_loses_bool.md` |

Nothing is left on the "still to verify" list.

A ninth CLOSED report's analysis
(`CODEGEN_same_bare_name_struct_collision_across_modules.md`) was
re-derived rather than trusted, and that re-derivation is what found the
bug was still live — the "unfixable today" framing turned out to rest on a
*different* bug (`module.Class(...)` construction) that had since been
fixed, which is what made a runnable repro exist. It was then fixed
properly, on 2026-09-29: two same-bare-named structs in different modules
now get distinct module-qualified C identities instead of sharing one field
table and one typedef, so a loser's `str` field no longer lands in the
winner's `int64_t` slot as a heap address. Verified against CPython on four
shapes, and on the real trigger this doc originally named — `Lib/tkinter/
filedialog.py`, whose closure holds THREE same-named `Dialog` classes,
which the unfixed compiler collapsed into a single `typedef struct Dialog`
and which now come out as `tkinter_dialog_Dialog` and
`tkinter_simpledialog_Dialog`. **Doc deleted** (CLAUDE.md: a fully-fixed
bug's report is removed), so unlike the eight above it is not being kept as
a monument to re-verify.

The two-step sequence is worth keeping as a lesson rather than as a doc:
every entry in this table was "OPEN" partly because a *larger* bug sat in
front of it, and fixing the larger one is what turned the smaller one from
unreachable into a two-hour fix. "No program can exhibit this" is a claim
about the bugs in front of it, not about the bug.

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
| `import p.sub` + `p.sub.f(14)` exits 1 with no output, on both pipelines | `bugs/CODEGEN_import_dotted_name_two_hop_attribute_call_exits_1.md` — itself since fixed and deleted; see the 2026-10-01 section below |
| `str()`/`%s` never consult `__str__`; a struct inside a list/tuple reprs as a raw pointer | `bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md` |

CLOSED 2026-09-30 on `work/codegen-old-divergences`: the "return type is
`int64_t` when its only `return` is a method call" row is gone — the method-call
case of the return-type inference now reads the callee's registered type out of
`func_return_types` under its MANGLED name (via a third overlay in
`_infer_return_type_with_locals`: a local bound to a registered struct's
constructor is visible as `<Struct> *`, which is what `_quick_type`'s
method-call branch is gated on). Measured: `return p.__repr__()` printed
`R<a>` on CPython and `4380508000` on the compiled path, and now prints `R<a>`
on both. Its doc is deleted; the regression is `method_call_result` in
`test_runtime_diff.py`, which the harness now also cross-checks against
CPython.

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

### 2026-09-30: one removal, and the blocker turned out to be a different bug than the doc claimed

`CODEGEN_method_call_on_struct_param_mistyped.md` (the PARTIAL row it came
from) is **fixed and deleted**. All eight method-name rows, the q3
two-spelling contrast, the single-file cross-module row and the
link-mode cross-module row now match CPython on the real
`python3 fire.py build` pipeline, with `test_gimple_runner.py` 176/176 and
`test_link_mode.py` 9 passed / 1 failed — that one failure being the
pre-existing `from . import SUB` row in the table above, re-measured on a
reversed diff, not a regression.

The interesting part is why its last row was still red, because the doc's
own explanation was wrong twice over. It said the row was blocked by
`CODEGEN_same_bare_name_struct_collision_across_modules.md`, whose §4 it
quoted ("`module.Class(...)` construction is unresolved on every path"). It
was not that bug: a same-bare-name collision needs two same-named classes,
and the row has one. And the blocker was not "every path" — the
`from insp import Parameter` spelling of the *same* program printed `v`
through the *same* link-mode build. The real cause was that
`_register_link_imports` (`mojo/backend_gimple/emit_resolve.py`) scanned
only `FromImportStmt`, so a module reached through its own module object
was never a candidate for `_link_inline_modules` and never appeared in the
client's translation unit: `insp.Parameter(...)` fell to the generic
scalar-receiver stub and the module HANDLE came back as the object.

That is cause (c) from the list below — *closed on a narrower spelling than
the one still broken* — the third time it has produced a removal from this
directory, and the first time the narrower spelling was **import
resolution** rather than pipeline. Which is the transferable lesson: "the
other spelling" is not a safe place to stop, and the cheapest way to check
is to write both spellings of the same program down side by side and diff
their answers, which took two builds here and would have closed the row on
2026-09-27.

The residue the closure turned up belonged to a different bug. It was
**fixed and deleted on 2026-10-02**: a cross-module struct constructor
called at **module scope** (rather than inside a function) was mistyped
in BOTH import spellings — a pointer decimal, exit 0. The cause was a
missing set of CALL SITES, not a missing seam: the cross-module
constructor field-type hint pre-pass in `module_gen.py` collected its
sites by walking `FunctionDef` bodies only, so a module-level
`insp.Parameter('v', 7)` was in no collected set and the imported module
compiled `self.v = v` at the `int64_t` default against a `char *` field.
It was filed on 2026-09-30, three days after the row above, by the same
kind of one-spelling-at-a-time reading that row records — and the two
are the same lesson from opposite ends, since this one's own first
measurement blamed module SCOPE when the function-scope spelling of the
same two lines had been right all along.

### 2026-10-01: the two-hop row above, and a fourth instance of cause (c) — closed by a MERGE, not by an edit

`CODEGEN_import_dotted_name_two_hop_attribute_call_exits_1.md` (the residue row
in the 2026-09-29 table) is **fixed and deleted**. `import a.b` binds `a`, so
`a.b.f(...)` is a two-hop attribute call whose receiver is the SUBMODULE; both
pipelines now match CPython (`42`), measured in `test_gimple.py`'s
`dotted_import_two_hop_attribute_call`, which is the doc's own regression.

Worth recording because **nothing was wrong with either fix**. `a0691784`
landed the two-hop fix, including the link-mode half: it added an
`elif isinstance(stmt, ImportStmt)` arm to `_register_link_imports`'s `scan`
ladder (`mojo/backend_gimple/emit_resolve.py`) that registers a dotted plain
import's submodule for inlining. `1f7717c1` landed later and turned the SAME
ladder's FIRST arm into `if isinstance(stmt, ImportStmt)` — for `import M` +
`M.Class`. Two `ImportStmt` arms in one `if`/`elif` chain, and the second one
became unreachable code: no error, no warning, no test failure in the branch
that wrote it. The bug was reported fixed and its doc deleted while half of it
sat dead in the tree.

So this is cause (c) from the list above — *closed on a narrower spelling than
the one still broken* — with a new mechanism: the narrowness was introduced by
the SECOND fix, so no single branch's own gate could have caught it. The
detectable form is mundane and worth writing down: **a regression test that
lives in the tree is not evidence that the change behind it is live.** Here
`test_gimple.py` was present, named, and asserting the right answer; it went
red the moment the batch landed, which is the only reason this was found at
all. The transferable check for the next `if`/`elif` chain a merge touches:
grep the function for the type each arm matches and check that no two arms
match the same node type.

Two smaller things the same pass turned up, both recorded here because both
were silent:

- `test_gimple.py`'s two-hop case **skipped itself** — counting neither a pass
  nor a fail, so it vanished from the tally — whenever `$TMPDIR` landed inside
  the checkout, on the ground that the module-qualified-call fallback is
  disabled there. That ground went stale when `_lower_method_call`'s
  `_mgc_is_selfhost` check became
  `mojo/middle/methods_shared.py::_is_selfhost_source_file`, which asks
  whether the file is one of the COMPILER'S OWN modules and deliberately not
  whether it merely sits under the install directory. Verified on this tree: a
  scratch package at `<checkout>/.tmp/x/q/main.py` is False,
  `<checkout>/mojo/middle/x.py` and `<checkout>/gimple_codegen.py` are True.
  The case now runs in both locations, as
  `test_link_mode.py`'s `test_bare_submodule_import_call_inside_source_tree`
  already did for the single-hop spelling. A skip that counts nothing is worse
  than a missing test, because it reads as coverage.
- The first two rows of the same 2026-09-29 table
  (`CODEGEN_link_mode_bare_submodule_marker_call_silent_wrong_value.md`,
  `CODEGEN_reexported_function_import_qualifier_names_the_wrong_module.md`)
  name docs that no longer exist either, so this table now has three dangling
  targets rather than one. Their fixes are visible in `test_link_mode.py`
  (`test_bare_submodule_import_call` and friends all pass), so the rows are
  stale bookkeeping rather than open work — NOT reconciled here, because they
  belong to other branches' closures and re-deriving what those docs said
  needs the history spelunking pass the rot section at the end already
  describes.

## Notes for future sessions

- **The three unrun test files are now registered** (corrected 2026-09-29;
  the note this replaces was written 2026-09-26 and is kept because the *reason*
  it matters has not changed). `test_gimple_runner.py` is `gimplerunner`,
  `test_gimple_generator_runner.py` is `gimplegenerators` (both in `check`
  and `gate`), and `test_coro_nested_async_capture.py` is
  `coro-nested-capture` (in `gate`/`coroutine`, and its pre-rename
  `mojo_*`-runtime source list is fixed). The history is still worth reading:
  a correct fix sat **red** in `test_gimple_runner.py` for a full pass
  because nothing ran it, which is what made the structural fix worth doing.
  A fourth file remains in no bucket — `test_gimple_async_runner.py` is
  registered as `gimple-async-runner` but carries `expect=` (36 failing), so
  it runs and its result is not yet evidence of anything.

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
