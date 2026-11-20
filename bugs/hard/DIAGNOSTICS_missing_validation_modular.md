# DIAGNOSTICS: missing validation/error reporting for modular test cases

SPLIT: DIAGNOSTICS_missing_validation_modular-part1, DIAGNOSTICS_missing_validation_modular-part2, DIAGNOSTICS_missing_validation_modular-part3, DIAGNOSTICS_missing_validation_modular-part5, DIAGNOSTICS_missing_validation_modular-part6

## Symptom
Modular test files expect compile-time errors/diagnostics that our compiler does not produce (it compiles them successfully). These are cases where modular's compiler rejects invalid code but ours accepts it.

## Categories

### A. Missing validation (real bugs — should catch these) ~25 files
- Comptime asserts: comptime_assert.mojo, comptime_assert_tstring.mojo
- Type/conformance: invalid_downcast_error.mojo, struct_conditional_trait_conformance_errors.mojo, defaulted_trait_method_bad_conformance.mojo, never_conforming_no_synthesis.mojo, not_conformance.mojo
- Constraints: autoparam_dependency_errors.mojo, failed_binding_deferrals.mojo, tuple_contains_type_mismatch_error.mojo, tuple_first_of_error.mojo, where_message.mojo, moco_4400_no_crash_on_bind_parameter.mojo
- Imports: import_error_location.mojo, import_fn_scope_ambiguous.mojo, import_qualified_member_no_leak.mojo, import_mojoc_conformance_error.mojo, import_mojoc_implicit_default_param.mojo, import_dual_mount_mojoc.mojo, mojo_import_case_sensitive_error.mojo, docstring_self_import.mojo
- Error tolerance/recovery: error_tolerance.mojo, elaboration_error_recursion1.mojo, error_handling.mojo, enum_exhaustive_errors.mojo
- Other: align_decorator_parametric_error.mojo, assert_failure_message.mojo, identifier_source_range.mojo, variadic_kwargs.mojo, mojo_package_moco_773.mojo

### B. Diagnostic formatting (compare our output to theirs) ~10 files
- diagnostics_in_missing_locs.mojo, diagnostics_in_missing_locs_imports.mojo, diagnostic_format.mojo, kgen_lsp_check_parse_error.mojo, invalid_downcast_error.mojo (diagnostic part)
- All five formatting files now pass their FileCheck lines (static declaration pass, `fire build` diagnostics; formatting bug closed 2026-11-14).

### C. GPU/offload (we target GPU — see bugs/hard/GPU_offload_validation_modular.md)
- compile_offload_*, enqueue_function_device_passable_closure_arg_*, sanitize_address*.mojo, op_with_unsupported_type_error.mojo, end_to_end_thunk_with_direct_compile.mojo, simd_bad_size_lowering.mojo

### D. Modular-specific/CLI (not our bugs)
- mojo_doc_*, mojo_build_*, mojo_run_*, mojo_package_*, missing_option_value.mojo, mojo_lldb_version.mojo, literals.mojo, explicit_destroy.mojo, indirect_call.mojo, raise_and_try.mojo, layout_copy_error.mojo, inline_mlir_op_fstring_elaborate_errors.mojo, inline_decorator_errors.mojo, debuginfo_raise_hook.mojo

## Full list
See build/checkfail_candidates.json (61 error-like cases).

## Notes
- Our compiler currently produces no errors for these; it compiles them successfully.
- Need to add validation for category A (real bugs).
- Category B: compare our diagnostic output to modular's; file individual bugs if ours is worse.
- Category C: we target GPU offloading, so these validations are relevant (see GPU bug report).
- Category D: modular-specific features/CLI, likely out of scope.

## Status (merged from work/bug-mid-diagnostics-missing-validation-m branches)
- **Landed (partial):** `comptime assert` statements with provably-false
  conditions now fail compilation with a diagnostic
  (`comptime assertion failed: ...`) in the gimple backend, instead of being
  silently accepted/emitted as a runtime trap. `eval_const_bool`/`_state`
  determines provable falsehood; when a `comptime if` degrades to runtime
  (conditions unknown) the assert is treated as non-fatal to avoid false
  positives in generic fallback branches (e.g. DType-category `else` guards
  whose conditions our comptime evaluator cannot yet resolve).
  Regression: `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up):** comptime diagnostic messages are now evaluated, not
  lowered to compiler temp names. `mojo/middle/comptime.py` folds
  `String(int/bool)` and string `+` concatenation at compile time, so messages
  like `"got " + String(x)` with bound param values produce the human-readable
  message. Regression added to `test_comptime_assert_diagnostic.py`.
- **Landed (follow-up, branch 4715):** compile-time diagnostics for the
  `constrained[...]()` builtin form (and paren form) in the gimple backend
  (`mojo/backend_gimple/emit_calls.py`). A provably-false condition fails with
  `constraint failed: <message>`. Unknown conditions treated conservatively.
  Also fixed a duplicate runtime-assert lowering in
  `mojo/backend_gimple/emit_stmts.py`. Regression:
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6289):** `mojo/middle/comptime.py` folds DType
  values (`DType.int32`) and DType predicate methods (`is_integral`,
  `is_floating_point`, `is_signed`, `is_unsigned`, `is_numeric`, `is_bool`,
  `is_index`, `is_float8`, `is_half_float`) during compile-time constant
  evaluation. Regression: `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 7836):** `mojo/backend_gimple/emit_resolve.py`
  re-raises compile-time diagnostics (`constraint failed` / `comptime assertion
  failed` RuntimeErrors) raised while compiling an elaborated generic struct
  instantiation (previously swallowed). Regression:
  `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 794):** `fire_compiler.py` tokenizer fix: a line
  ending with a string literal no longer suppresses DEDENTs across blank lines
  when the next significant line is not a string continuation. Regression:
  `test_comptime_dtype_diagnostic.py`.
- **Landed (follow-up, branch 3407):** comptime evaluation of interpolated
  string literals (`t"..."` / `f"..."`) in diagnostic messages
  (`mojo/middle/comptime.py`). Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 4840):** short-circuit boolean folding for
  `and`/`or` in compile-time constant evaluation (`mojo/middle/comptime.py`).
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6439):** comptime-for unrolling binds
  `range(...)`/`product(range(...))` induction targets in `gen._comptime_vals`
  (`mojo/backend_gimple/emit_funcs.py`). Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 8406):** comptime-for unrolling over constant
  `ListExpr`/`TupleExpr` iterables binds loop variables in `gen._comptime_vals`.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 223):** comptime-for unrolling over constant
  list/tuple iterables with tuple-unpacking targets. Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 1584):** comptime-for unrolling over non-literal
  iterables that resolve via `gen._eval_const` to a constant list/tuple.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, 2026-11-09):** compile-time diagnostic for an import
  that names no resolvable module — `error: unable to locate module 'X'` at
  the import's line, naming the FIRST missing component (`import a.b.c` with
  `a` present → `c`; a wrong-case/unresolved root → the root), matching
  modular's `import_error_location.mojo` and
  `mojo_import_case_sensitive_error.mojo`. Enforced in BOTH the inline path
  (`_compile_imported_module`, used by `fire.py build`'s fallback) and the
  link path (`_register_link_imports`, used by `driver.compile_program`),
  so `fire.py build` fails with exit 1 instead of silently accepting the
  import. A module that is a real Python module is still provided by the
  runtime (importlib) and is not an error; a `from X import Y` joined
  candidate (`X.Y`) is not treated as a missing module because `Y` may be a
  symbol defined in `X`. Regression:
  `test_import_missing_module_diagnostic.py`.
- **Landed (follow-up, 2026-11-09):** `error: functions must not declare both
  an 'out' argument and a return type` at the return type's location
  (`mojo_package_moco_773.mojo`). Regression:
  `test_out_param_return_type_diagnostic.py`.
- **Landed (2026-11-11):** `where (cond, "message")` is enforced on functions
  and structs. The parser keeps struct `where` clauses and accepts repeated
  `where` keywords; `elaborate.check_where_clauses` folds each clause with
  `eval_const_bool_state` against the concrete type args, and a provably false
  one raises `WhereConformanceError` (a ConformanceError), which the struct
  instantiation path re-raises. An undecided clause is accepted as before, and
  the DType regex checks run only when a clause is undecided. Regression:
  `test_where_message_diagnostic.py`. Not done: the `lacking evidence` note.
- **Landed (2026-11-11):** `StaticString(_get_kgen_string["text"]())` in a
  `comptime assert` / `constrained` message folds to its text
  (`comptime.eval_const`, by name, index folded first). An unknown index stays
  unfolded. Regression: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (2026-11-11):** `comptime for` over a list comprehension
  (`[i * 2 for i in range(3)]`, with `if` filters, bound by name or direct):
  `comptime.eval_const` folds a list comprehension to its element values, so
  the unroller binds the loop variable and `comptime assert` / `constrained`
  fire inside it. An unknown element or iterable is left unfolded. Regression:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Landed (2026-11-11):** bare continuation lines of string literals fold into
  one message (`comptime assert c, "a"` / more-indented `" b"`): the tokenizer
  drops the NEWLINE between them (`fire_compiler.py::py_tokenize`). Same-indent
  string lines and blank-line-separated ones stay separate. Regression:
  `test_comptime_assert_diagnostic.py`.
- **Landed (2026-11-11):** interpreter runs the `constrained[cond, msg]()`
  builtin: a false condition raises `constraint failed: <msg>` (exit nonzero),
  a true one is a no-op; a user-bound `constrained` name is not intercepted.
  The paren form `constrained(cond, msg)` is not handled. Regression:
  `test_interpreter_constrained_diagnostic.py`.
- **Landed (2026-11-11):** interpreter `assert` failure (`python3 fire.py run`)
  now prints the same `Assert Error: <msg>` prefix as the compiled path, with
  the default `assert failed` when no message is given. Regression:
  `test_interpreter_assert_message.py`.
- **Landed (follow-up, 2026-11-09):** runtime `assert` failure now prints
  `Assert Error: <msg>` (`assert_failure_message.mojo`), via the runtime's
  `mojo_print_stderr` helper (`stderr` is a macOS macro, illegal in gimple).
  Also: `except <name>:` (bare lowercase name, no `as`) is a catch-all
  binding, matching modular's `parseTryStmt` target behaviour
  (`error_handling.mojo`); `except <Type>:` / `except <Type> as <name>:`
  remain type patterns for Python compatibility.
- **Landed (follow-up, 2026-11-09):** `error: import of 'X' is ambiguous` at
  the second of two same-name imports from different modules into one
  function scope, with notes naming where each module declares it
  (`import_fn_scope_ambiguous.mojo`). Regression:
  `test_ambiguous_import_diagnostic.py`.
- **Landed (follow-up, 2026-11-09):** generic `where`-clause / trait-bound
  enforcement at call sites — `error: invalid call to '<fn>': violated
  constraint` when the supplied type arguments cannot satisfy the generic's
  `where` clause (`where T.is_floating_point()` etc.) or a trait bound. The
  in-TU pre-pass now runs `check_bounds` before materializing an
  instantiation, and a `ConformanceError` from the `.o` route surfaces
  instead of falling through to the silent stub path. Regression:
  `test_where_clause_call_site_diagnostic.py`. (Plan §1; the modular
  `tuple_*` tests additionally need the stdlib `where` clauses, which this
  tree's stdlib does not carry.)
- **Landed (follow-up, 2026-11-09):** a qualified access `mod.name` must
  resolve `name` against `mod` only — `other.shared_fn` (an `__init__`
  re-export) and `other.helpers` (a sibling module) are hard errors
  (`import_qualified_member_no_leak.mojo`); a real submodule (`mod.sub`) or
  a declared name still resolves. Regression:
  `test_qualified_member_no_leak.py`.
- **Landed (2026-11-13):** `in` / `not in` on a provably scalar container type
  with no `__contains__` is a compile-time error in the gimple lowering, with
  the container type's spelling in the message
  (`'Int' does not implement the '__contains__' method`, and likewise
  `Float64`/`Bool`). Type-erased/module-global and unresolved-generic cases
  stay conservative so runtime dispatch is preserved. Regression:
  `test_contains_method_diagnostic.py`.
- **Landed (follow-up, 2026-11-13):** the part3 check above no longer reads
  `_quick_type`'s `int64_t` FALLBACK as a proven Int — that default is the
  type-erased box, which may hold a container, and the gate's `stdlib-dylib`
  job went red on it: six stdlib modules (compile.mojo's `content in
  String(self)` among them) fell back to source on `'Int' does not implement
  the '__contains__' method`. `emit_exprs.py::_definitive_scalar_type` now
  proves the kind by shape/binding/known-callee-return only (`_call_
  provably_returns_int` mirrors the estimator's specific int rows — scalar
  builtins, scalar ctors, a recorded `-> Int`; member/subscript calls are
  never proven), and the container-yielding ops `+`/`*`/`|`/`&`/`^`/`-`/`%`/
  `and`/`or` require a proof on BOTH operands. Generated C for previously
  succeeding modules is byte-identical; the `stdlib-dylib` ratchet is green
  again (0 skips). Regressions added to `test_contains_method_diagnostic.py`
  (unrecorded call, erased operands, known-int calls).
- **Landed (follow-up, branch 3096):** `eval_const_int` resolves `IdentExpr`
  comptime bindings, enabling `range(...)` bounds that are comptime variables.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 4910):** comptime folding of `len()` for
  comptime-known `list`/`tuple`/`str` in `eval_const`, `_const_foldable`,
  `eval_const_int`. Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 6270):** comptime folding of
  `SubscriptExpr`/`SliceExpr` over comptime-known `list`/`tuple`/`str`;
  comptime-for unroller treats comptime-known `str` iterables as unrollable.
  Regressions: `test_comptime_assert_diagnostic.py`,
  `test_constrained_diagnostic.py`.
- **Landed (follow-up, branch 7781):** comptime folding of `DictExpr` literals
  and `len()`/subscript on comptime-known `dict` values. Regressions:
  `test_comptime_assert_diagnostic.py`, `test_constrained_diagnostic.py`.
- **Still open (large):** remainder of the umbrella — comptime-assert/
  `constrained` cases with incomplete condition evaluation (DType predicates on
  comptime params in generic instantiations bypassing elaboration; reflection-
  driven messages like `StaticString(_get_kgen_string[...])`), generic/trait-
  reflection conditions, non-gimple/formal backends, comptime-for shapes beyond
  the gimple unroller (DType/variadic iterables, computed/non-foldable
  iterables, comptime-known `dict` iteration, local `alias` bindings not always
  visible), type/trait conformance diagnostics (conditional conformance,
  defaulted trait methods, enum `_enum_is_exhaustive`, downcast witness
  tables), constraint diagnostics on tuple methods (`__contains__` /
  `first_of`), inferred-parameter dependency errors, binding deferrals,
  elaboration recursion detection, `@align` parametric validation, MLIR type
  annotations, LSP error recovery, docstring code-block self-import, and the
  mojoc/precompiled import errors. Landed 2026-11-09: missing-module,
  out+return-type, assert message, `except <name>:` binding, ambiguous
  same-name import, qualified-member leak. `build/checkfail_candidates.json`
  not present in this worktree; re-run `tools/collect_checkfail.py` against
  the modular suite to refresh/prioritize.

## Status (2026-11-14): measured against the real FileCheck lines

`tools/modular_filecheck.py <test>.mojo...` (new) runs a modular test through
`fire.py build` and its own FileCheck lines. Rollup siblings first: the four
formatting files `diagnostics_in_missing_locs.mojo`,
`diagnostics_in_missing_locs_imports.mojo`, `diagnostic_format.mojo` and
`kgen_lsp_check_parse_error.mojo` now PASS (the static declaration pass in
`myinterpreter.static_module_diagnostics`, run by `fire run`, `fire build` and the
bare compile-and-run path; `--Werror` supported); `invalid_downcast_error.mojo`
is part 5.

Category A, measured (`rc` = our exit code):

| file | verdict | note |
|---|---|---|
| comptime_assert_tstring.mojo | PASS | |
| error_tolerance.mojo | PASS | |
| defaulted_trait_method_bad_conformance.mojo | FAIL rc=1 | wrong/missing diagnostic text |
| autoparam_dependency_errors.mojo | FAIL rc=1 | |
| failed_binding_deferrals.mojo | FAIL rc=1 | |
| mojo_import_case_sensitive_error.mojo | FAIL rc=1 | needs `-I` dir handling in the RUN line |
| identifier_source_range.mojo | FAIL rc=1 | |
| tuple_first_of_error.mojo, tuple_contains_type_mismatch_error.mojo | FAIL rc=0 | need stdlib `Tuple` element-type checking (a real type checker: `UInt8(1) in ints`) |
| moco_4400_no_crash_on_bind_parameter.mojo, enum_exhaustive_errors.mojo, align_decorator_parametric_error.mojo, assert_failure_message.mojo | FAIL rc=0 | accepted silently |
| comptime_assert.mojo, never_conforming_no_synthesis.mojo | TIMEOUT (>60 s cold) | not measured |
| not_conformance.mojo, where_message.mojo, variadic_kwargs.mojo | FAIL | `%parse-mojo-isolated | FileCheck` on an MLIR dump, not a diagnostic: cannot pass by construction |
| struct_conditional_trait_conformance_errors.mojo, import_*(split-input-file) | UNSUPPORTED by the harness | `-verify-diagnostics` / `-split-input-file` |

**2026-11-14 (later): `align_decorator_parametric_error.mojo` is fixed on
this tree** (`43bd3dcba`). The table above records it as `FAIL rc=0 ...
accepted silently`, measured through `tools/modular_filecheck.py` (whose
`FIRE` is the mojo-reference checkout, not this tree). Measured here,
`fire.py build` also exited 0 and built a binary, so it was a real miss:
`_check_fn_signature_binding_violations` iterated `fn.params` only, and a
generic-struct mention in a RETURN type -- `@align(calc(alignment))` on
`struct Aligned[...]`, used as `-> Aligned[23]` -- was never
instantiation-checked, because `@align` was validated only on the
construction path. It now checks the return type too, through the same
`_validate_align_decorators_for_struct`. The canonical file fails with
exactly its two CHECK lines (`function instantiation failed`; `struct
alignment must be a positive power of 2, got 69`).

Next, in order of how much of it the static pass already gives: the rc=1 ones
(a diagnostic is produced but differs: capture `tools/mojo build` output next to
ours and fix the delta, as was done for diagnostics_in_missing_locs), then the
rc=0 ones that are declaration-level (`enum_exhaustive_errors`,
`align_decorator_parametric_error`, `moco_4400`), leaving the type-checker ones
(`tuple_*`) for last.

## 2026-11-16 (wakeup 41): `moco_4400` re-measured, with a 30-line repro

`fire.py build` on the Modular file exits **0** (still a miss). The gap is not
the message -- `does not implement all requirements for 'Iterable'` is produced
by the elaborator, and `test_trait_requirement_evidence_diagnostic.py` pins it
by calling `elaborate.Elaborator().elaborate_generic_call(src, 'needs_iterator',
['S[NotMovable]'])` DIRECTLY. So the machinery works when triggered; the
whole-program path never triggers it for this call.

Minimal repro (30 lines, `fire.py build` exit 0, no diagnostic):

```mojo
struct S[T: AnyType](
    Copyable where conforms_to(T, Copyable),
    Iterable where conforms_to(T, Movable),
    Movable,
):
    var _v: Self.T
    def __iter__(ref self) -> Self where conforms_to(Self.T, Copyable):
        return self.copy()
    def __next__(mut self) raises StopIteration -> Self.T where conforms_to(Self.T, Movable):
        raise StopIteration()

struct NotMovable:
    var x: Int

def needs_iterator[I: Iterator](x: I):
    pass

def foo():
    var s = S(NotMovable(1))
    needs_iterator(s)
```

`S[NotMovable]` does not conform to `Iterator` (its conformance is conditional
on `T: Movable`, and `NotMovable` is not `Movable`), so `needs_iterator(s)`
must be rejected. Measured the same day: `enum_exhaustive_errors`,
`moco_4400_no_crash_on_bind_parameter` and `tuple_first_of_error` all still
exit 0; `align_decorator_parametric_error` exits 1 (a diagnostic, delta
uncompared).

### Why the build never triggers it (wakeup 42)

`foo`'s body emits a **bare** call -- `_t9 = needs_iterator (s);` -- with no
mangled suffix and no instantiation. The reason is one line:

```python
# mojo/backend_gimple/emit_resolve.py:3555, in _elaborate_generic_call
source = gen._imported_generics.get(g)
if not source:
    return None
```

`_elaborate_generic_call` is gated on the callee being an **imported** generic.
`needs_iterator` is defined in the SAME module, so `source` is None and the
function declines before lowering anything. Every later arm -- the explicit
bracket path, the inferred path, and the `except` that turns a
`ConformanceError` into `error: invalid call to '<fn>': violated constraint`
(line 3789) -- is unreachable for a same-module generic. That is exactly why
the unit test passes (it calls `elaborate_generic_call` directly, past the
gate) while `fire.py build` exits 0.

Two consequences, not one: the missing MOCO-4400 diagnostic, and a bare call to
a symbol nothing defines. Same-module generic calls are elaborated by the
in-TU pre-pass (`elab_intu`), which is also where the conformance check would
have to be wired for this case.

### The full chain (wakeup 44) -- a discriminator blind spot, not a missing check

Probed end to end on the 30-line repro:

1. `needs_iterator` IS registered for the same module -- `module_gen.py:12246`
   puts every local generic into `_imported_generics` under
   `_current_filename`, and `_generic_source_text` (:5137) resolves that back to
   the in-memory text. Probed: `_elaborate_generic_call` is entered with
   `explicit=False source='.../m.mojo'`.
2. So the inferred branch runs and calls `elaborate_generic_call_inferred`,
   which infers `S[NotMovable]` and calls `elaborate_generic_call` -- which
   raises `ConformanceError` for the violated `Iterator` bound.
3. **`elaborate.py:3776` swallows it.** The handler's own discriminator is
   `if any(not inferred_ctype_is_specific(ct) for ct in arg_ctypes): return None`
   -- i.e. decline when an argument's C type is a placeholder. Measured:
   `inferred_ctype_is_specific('S *')` is **False**, along with `int64_t`,
   `char`, `int`, `MojoList *`, `NotMovable *`; only `double` is True.
4. So a REAL struct pointer is indistinguishable, to that predicate, from an
   erased `int64_t`/`char` -- which is exactly the case the swallow exists to
   protect (the six stdlib files listed in its comment). The caller's real Mojo
   type is not available to disambiguate: `_constructed_struct_type`
   (emit_resolve.py:3514) recovers a type only for a direct constructor call
   (`Foo()`), and here the argument is the IdentExpr `s`.

The fix is therefore in the discriminator, not in the check: it needs the
argument's real Mojo type (from the local's declared type) rather than the C
type, so a genuine `S[NotMovable]` is distinguished from an erased scalar.

## 2026-11-16 (wakeup 45): the rc=1 table is stale, and the real delta is the
## source-range prefix

Ran `tools/modular_filecheck.py` over the rc=1/rc=0 candidates. Note first that
the tool's `FIRE` is hardcoded to `/Users/mrs/net/chatgpt/claude/mojo-reference/
fire.py` -- the OTHER checkout, not this tree -- so these verdicts describe that
tree; the two PASSes are still meaningful as "the delta is closed there".

| file | verdict |
|---|---|
| `defaulted_trait_method_bad_conformance.mojo` | **PASS** (rc=1) |
| `align_decorator_parametric_error.mojo` | **PASS** (rc=1) |
| `autoparam_dependency_errors.mojo` | FAIL rc=1 -- `CHECK: expected string not found in input` |
| `failed_binding_deferrals.mojo` | FAIL rc=1 -- same |
| `identifier_source_range.mojo` | FAIL rc=0 |
| `moco_4400_no_crash_on_bind_parameter.mojo` | TIMEOUT |
| `enum_exhaustive_errors.mojo` | TIMEOUT |

So the umbrella's table is stale in both directions: two of its `rc=1` rows now
PASS, and `align_decorator_parametric_error` has moved off the `rc=0` list
(verified directly: our output is `function instantiation failed` / `struct
alignment must be a positive power of 2, got 69`, both CHECK lines present).

The two FAILs share one concrete delta. Their CHECK lines are written as

    # CHECK: [[@LINE+3]]:{{[0-9]+}}: error: violated constraint
    # CHECK: [[@LINE+2]]:{{[0-9]+}}: error: inferred parameter of type ...

i.e. they require a `line:col:` SOURCE-RANGE prefix on the diagnostic. Our
output for the same files is `error: violated constraint` and
`error: inferred parameter of type 'Pair[c, c]' cannot depend on ...` with no
prefix, so FileCheck cannot match. That is the same theme as
`identifier_source_range.mojo`, and it is a narrower, more tractable target
than "the type checker ones" the umbrella lists last.

### The delta is one line number (wakeup 46)

Our output for `failed_binding_deferrals.mojo` is

    Error building: .../failed_binding_deferrals.mojo:32:0: error: violated constraint

The CHECK is `# CHECK: [[@LINE+3]]:{{[0-9]+}}: error: violated constraint` written
on file line 30, so it wants **line 33** -- which is
`    x: NeedsCopyablePos[CondCopyable[U], 0]`, the parameter carrying the
violated binding. We report **line 32**, `def failed_binding[...](`.

So the prefix format is already right and the column already matches
(`{{[0-9]+}}` accepts `0`); the ONLY disagreement is WHICH LINE the diagnostic
anchors to. The range is attached at `module_gen.py:5179-5183` (and the twin at
5194-5197) from `fn.line`/`fn.col` -- the FUNCTION/STRUCT position -- while
Modular anchors at the offending parameter. `check_where_clauses` raises
`WhereConformanceError`; making it name the parameter would close this.

Same shape expected for `autoparam_dependency_errors` (its CHECKs are also
`[[@LINE+n]]:{{[0-9]+}}: error: ...`).

### `enum_exhaustive_errors` isolated (wakeup 63)

Re-measured: `fire.py build` exits **0** on the Modular file, so the miss is
real. But it is NOT the general "comptime member type" check:

* the general check EXISTS and is pinned --
  `test_trait_comptime_member_conformance_diagnostic.py` PASSes, including
  `test_enum_exhaustive_mistyped`, which is exactly this shape with an
  EXPLICIT `__enum Mistyped(EnumLike)`;
* the Modular file declares no `EnumLike` at all -- it is
  `__enum Mistyped(ImplicitlyCopyable, Writable)` -- and FileCheck expects the
  diagnostic to name `EnumLike`.

Probed the trait list (`Writable`, `ImplicitlyCopyable`, both): all exit 0.
**The source, located (same day).** Modular's parser:
`mojo/lib/MojoParser/StructEmitter.cpp:1586`
(`enumExhaustiveDeclFailedConformance`) -- "Whether a written
`_enum_is_exhaustive` of `enumDecl` fails conformance to `EnumLike` (e.g. it is
not a `Bool`); it is the only member of that conformance a user can write. The
conformance reports the error."

So the requirement comes from a **compiler-synthesized `EnumLike` conformance
for the enum**, and `_enum_is_exhaustive: Bool` is a member of THAT builtin
trait. It is NOT the stdlib trait I first guessed: `std/builtin/enum_like.mojo`'s
`trait EnumLike` requires `_enum_case_names` / `_enum_case_types` /
`_enum_elt_type_for_case` / `_get_enum_discriminant` and does NOT mention
`_enum_is_exhaustive` (grep confirms the name appears nowhere in the stdlib
tree). My earlier attribution to the stdlib trait was wrong and is corrected
here.

Target, narrowed: synthesize the enum's `EnumLike` conformance with
`_enum_is_exhaustive: Bool`, and report through the existing
"does not implement all requirements" + "note: comptime member ... does not
conform to trait's required type ..." machinery -- both of which already work
for an explicit conformance.

### implementation target (wakeup 65)

Two probes bound it:

* `__enum Mistyped(EnumLike)` with the REAL stdlib trait imported
  (`from std.builtin.enum_like import EnumLike`) still exits 0 -- correctly, since
  that trait does not require `_enum_is_exhaustive`;
* our compiler contains **no builtin `EnumLike`**: grep for the name over
  `mojo/` + `fire_compiler.py` + `elaborate.py` returns only two COMMENTS
  (`fire_compiler.py:6163`, `elaborate.py:1559`), and builtin traits are not
  special-cased by name anywhere in the middle end (`ImplicitlyCopyable` likewise
  appears only in a comment). So the conformance our enum needs does not exist
  here at all.

What the fix therefore is: when an `__enum` is declared, synthesize its
`EnumLike` conformance with `comptime _enum_is_exhaustive: Bool` (the one
member a user may write), and let the existing conformance checker report the
violation. The checker is proven -- the pinned
`test_enum_exhaustive_mistyped` drives exactly this diagnostic through a
user-defined trait with the same requirement. Only the synthesis is missing.

**Why it is not a small patch:** the requirement list comes from a parsed
trait body (`fire_compiler.py:6163` -- only a value-less `comptime NAME: Type`
is a requirement), and the checker
(`elaborate.py:_comptime_member_requirement_errors`) only runs for a base the
struct actually lists. There is no builtin/prelude trait source in this tree
(grep: no `trait Writable` / `trait ImplicitlyCopyable` / prelude defs), and
`std/builtin/enum_like.mojo` does not exist in our stdlib. So the fix needs a
builtin `EnumLike` trait definition plus synthesizing the conformance on every
`__enum` -- a feature, not a patch. Filed as such rather than approximated by a
special case that would emit a "trait 'EnumLike' declared here" note with no
declaration behind it.

## Status (2026-11-19): signature diagnostics anchored at the parameter, all reported

Landed (measured with the real FileCheck lines, `fire.py build` + `FileCheck`):

* `failed_binding_deferrals.mojo` now PASSES. The `violated constraint` /
  `lacking evidence` diagnostics from `_check_fn_signature_binding_violations`
  are anchored at the OFFENDING PARAMETER (or the `->` return type), not at the
  `def`: `module_gen._signature_item_positions` reads the declaration text
  (`FunctionDef.params` carries no positions), skipping the `[...]` list and
  comments/strings. Falls back to the function position when unreadable.
* `_check_signature_binding_violations` collects every offending signature and
  raises them together (it used to stop at the first, which hid the
  `successful_binding` "lacking evidence" the second CHECK wants).
* `autoparam_dependency_errors.mojo` now PASSES. `fire_compiler`'s
  `_check_inferred_param_dependencies` and `_check_variadic_element_types` were
  run in sequence, so the first raise hid the second's diagnostic; they now
  report together.
* Regression: `test_signature_diagnostic_anchors.py`.

Remaining: the rest of the "Still open (large)" list above, notably the
`EnumLike` synthesis (`enum_exhaustive_errors`), the same-module generic
discriminator (`moco_4400`), `identifier_source_range`, and `tuple_*`. The
combined autoparam errors are ordered by check, not by source line.

## Status (2026-11-20): `moco_4400` — the 2026-11-16 chain is WRONG at step 2; the real blocker is the type of the local

Measured on the doc's 30-line repro (in-process `compile_to_gimple(do_imports=True)` from a real file; the
build is the same, exit 0):

* `needs_iterator(s)` IS reached: `elaborate_generic_call_inferred('needs_iterator', ['S *'])` runs.
* It returns `None` **before** any conformance check, not by swallowing a `ConformanceError`: `infer_type_args`
  cannot bind `I` from the bare C type `S *` (`c_to_mojo('S *')` is None by design), and `elaborate_generic_call`
  is never entered. The 11-16 note that "it infers `S[NotMovable]` and raises" held only for the direct unit
  test, which hands the elaborator the type text `S[NotMovable]`.
* So loosening the swallow's discriminator (`inferred_ctype_is_specific`, treating a pointer to a program
  struct as specific) changes nothing for this program: tried, no effect, reverted.
* Why `S *`: `var s = S(NotMovable(1))` is **not elaborated as a generic struct instance at all**.
  `_elaborate_generic_struct_call` (`emit_resolve.py`) takes the inferred-constructor path only for
  `gen._imported_generic_structs`, and `S` is defined in the SAME module, so the call lowers as the erased base
  struct and `_register_generic_struct` is never called (probed). The local's type is `S` with `T` erased;
  `NotMovable` is recorded nowhere.

Next step (a feature, not a patch): infer the type arguments of a same-module generic struct constructor
(`S(NotMovable(1))` -> `S[NotMovable]`) and record the local's Mojo type (`gen` has no per-local Mojo-type
table; `_proven_arg_mojo_type` knows only a parameter's annotation and a direct constructor call). Then
`_proven_arg_mojo_type` returns `S[NotMovable]` for the IdentExpr `s`, `infer_type_args` binds `I`, and the
existing `Iterator` conformance check fires (it is proven: `test_trait_requirement_evidence_diagnostic.py`).
The positive control to pin it with: the same program with a `Movable` payload must still compile.
