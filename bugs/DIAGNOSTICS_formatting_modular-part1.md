# DIAGNOSTICS: formatting comparison with modular (part 1)

## SPLIT: DIAGNOSTICS_formatting_modular-part1, DIAGNOSTICS_formatting_modular-part2, DIAGNOSTICS_formatting_modular-part3, DIAGNOSTICS_formatting_modular-part4, DIAGNOSTICS_formatting_modular-part5

## Symptom
Our diagnostic formatting for modular test cases does not match the expected format from the modular compiler. We need to compare our output with the modular reference and fix any discrepancies.

## Affected file
- `diagnostics_in_missing_locs.mojo`

## Acceptance
- The diagnostic output for `diagnostics_in_missing_locs.mojo` matches the modular reference format exactly.
- The status section of the bug doc reflects the fix.
- No other files are affected by this change.

## Notes
- This is part 1 of 5 parts for the `DIAGNOSTICS_formatting_modular` bug.
- The full list of affected files includes: `diagnostics_in_missing_locs.mojo`, `diagnostics_in_missing_locs_imports.mojo`, `diagnostic_format.mojo`, `kgen_lsp_check_parse_error.mojo`, and `invalid_downcast_error.mojo` (diagnostic part).
- This part focuses on `diagnostics_in_missing_locs.mojo`.

## Status

### 2026-11-14: planning round (no fix landed)

The test is a FileCheck test, not a golden-output file. Its spec is the `CHECK`
comments in `/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration/diagnostics_in_missing_locs.mojo`
(package: `.../mojo-integration/inputs/diags_package/__init__.mojo`). Its RUN lines
are `mojo precompile` -> `rm -r` source -> `not %mojo-build -I %t %s 2>&1 | FileCheck %s`.
Ground truth is the real compiler via `tools/mojo`; FileCheck is at
`/opt/homebrew/opt/llvm/bin/FileCheck`.

**Measured current state (base c0812fc19):**

1. Loading the package fails before any diagnostic is produced.
   `python3 fire.py run <copy of test with diags_package beside it>` exits 1 with
   `Error: .../diags_package/__init__.mojo:0:0: name 'implicit' is not defined`.
   Cause: `@implicit(deprecated=True)` on `DeprecatedImplicitConversion.__init__`
   is evaluated as an ordinary expression by `_apply_function_decorators`
   (`myinterpreter.py` ~3934). The decorator is not recognised as a Mojo
   declaration attribute. `@always_inline("builtin")` and `@fieldwise_init` also
   appear in the package and have not been checked yet.
2. With that decorator removed from a scratch copy, the remaining classes behave as follows:
   - `overloaded_function()` (three overloads, zero args) raises at runtime
     `Error: <file>:24:19: no overload of 'overloaded_function' matches 0 positional arg(s) and keyword(s) []`.
     One line, no candidate notes, and it is a runtime exception, not a
     compile-time error pass. The reference wants `error: no matching function in call to 'overloaded_function'`
     followed by one `candidate not viable: missing required argument: 'n'` note
     and `# CHECK-NEXT: def overloaded_function(n: Int)` synthetic signature per candidate.
   - `fn_missing_constraint[0]()` with `where n > 0` is NOT checked. The
     where-clause is ignored and the call proceeds. The reference wants
     `error: invalid call to 'fn_missing_constraint': violated constraint`.
   - Nothing in the tree prints `candidate not viable`, `violated constraint`,
     `does not implement all requirements`, `deprecated implicit conversion`,
     `lacking evidence`, `name conflict between parameter`, or
     `conflicting default implementations`. Grep confirms no such message exists
     in any `.py` outside `.claude/`.
3. Diagnostic format. Our top-level printer emits `Error: <path>:L:C: msg` on
   stderr. The reference emits `error: <msg>` / `note: <msg>` lines, with a
   source snippet or, for source-less declarations, a `# note - synthetic
   signature` line. Nothing in our tree prints `note:` lines or synthetic
   signatures.
4. No `precompile` analogue exists in this tree (`grep -n precompile fire.py` is empty),
   so there is no source-less package path to test against.
5. The compiled path (`timeout 300 python3 fire.py build` on the same scratch file, with
   `diags_package` removed and the `@implicit` decorator dropped) hit the 300 s timeout
   (exit 124) with no diagnostic output. The compiled path does not reach a diagnostic
   for this program in 5 minutes. It does not change the plan below.

**What the 11 expected diagnostic groups in this test require** (CHECK lines in the test,
in file order):

| # | CHECK message | infrastructure it needs |
|---|---|---|
| A | `invalid call to 'fn_missing_constraint': violated constraint` + constraint note with `($0 > Int(0))` and `expected '(n > Int(0))'` + `function declared here` with `def fn_missing_constraint[n: Int]() where (n > 0)` | compile-time where-clause evaluation at call sites with comptime args; printing a constraint in both the source-expression form and the substituted form |
| B | `no matching function in call to 'overloaded_function'` + three `candidate not viable: missing required argument` notes with synthetic signatures | overload-candidate collection with per-candidate rejection reason; synthetic signature printing |
| C | `no matching function in initialization` + `failed to infer parameter 'b' of parent struct 'PosOnlyStruct'` + `def __init__(out self) # note - generated function` + `struct PosOnlyStruct[a: Int, b: Int, /, c: Int = Int(9)]` | `@fieldwise_init` synthesis, parameter inference diagnostics, positional-only parameter `/` handling |
| D | `deprecated implicit conversion from 'IntLiteral[1]' to 'DeprecatedImplicitConversion'` + `call '...(...)' explicitly` + implicit constructor note | `@implicit(deprecated=True)` decorator support (see measurement 1) plus implicit-conversion diagnostics |
| E | `invalid call to 'my_unprovable_constraints': lacking evidence to prove correctness` + `cannot evaluate call to non-builtin function declared here` + `# note - synthetic signature` for `unfoldable_predicate` | `@always_inline("builtin")` foldability (`foldable_predicate` is builtin, `unfoldable_predicate` is not); a three-valued (true / false / unknown) constraint evaluator |
| F | `invalid call to 'unprovable_constraints'` (same family as E, no source snippet on the call-site note) | as E |
| G | `violated constraint` for `comptime _ = diags_package.constraint_fn[0, 1]` | as A, for a `comptime` binding |
| H | `name conflict between parameter 'a' in the default trait method and a parameter in the struct` + `trait method declared here` | trait default-method signature vs struct parameter list checking |
| I | `trait method requirement 'test' has conflicting default implementations in 'ConflictTraitMethod' and 'OtherConflictTraitMethod'` + `original default implementation` / `conflicting implementation` notes | trait-conformance pass over inherited trait default methods |
| J | `'StructViolation' does not implement all requirements for 'NoDefaultFunc'` + `required function 'doSomething' is not implemented` + `trait 'NoDefaultFunc' declared here` | struct-vs-trait requirement checker (required methods) |
| K | `ambiguous reference to 'handle': lacking evidence to select candidate` + `candidate is valid but cannot be selected until other candidates are disproved` + `required by trait method here` | candidate selection with evidence, including the unprovable case (conforms_to with an unrelated trait) |
| L | `does not implement all requirements` for `comptime N` / `var N`: `required member 'N' is not specified`, `comptime member 'N' type 'Bool' does not conform to trait's required type 'Int'` | trait `comptime` member checking (presence and type) |

Several CHECK lines carry FIXME comments that the reference itself does not
satisfy (for example constraint pretty-printing is `$0 > Int(0)` and the
parameter-bound form is unprinted). Our output has to reproduce the reference
exactly, including those quirks, not an improved version.

**Plan, in landing order. Each step is its own commit, and each has a named test.**

1. Decorator and declaration-attribute acceptance (shared infrastructure).
   `@implicit(deprecated=True)`, `@always_inline("builtin")` and `@fieldwise_init` must parse and be
   recorded on the declaration rather than evaluated as expressions. Touch point:
   `myinterpreter.py::_apply_function_decorators` and the matching compiled-path
   lowering in `gimple_codegen.py` if it reads decorators. Named test:
   `diags_package` imports without error (fire.py run of a file that only does
   `import diags_package`).
2. Diagnostic record type (shared infrastructure, consolidating the existing `Error:` prints).
   One `Diagnostic` class with severity, message, optional location, and a list of
   notes (each note optionally a synthetic-signature line). One printer that emits
   `error:` / `note:` with the reference wording. Migrate the existing `Error: ` callers in
   `fire.py` and `myinterpreter.py` to it. Named test: `FileCheck` over a small hand-written file
   with one error and one note, plus the existing tests unchanged.
3. Overload failure (group B, and C's parameter-inference failure). Extend `_NoOverloadMatch`
   into a candidate list with per-candidate reasons, and raise it as a compile-time
   Diagnostic instead of a runtime exception. Named test: the B block of the test under FileCheck.
4. Where-clause evaluation (groups A, E, F, G). Evaluate `where` at call sites with
   known comptime arguments. Three-valued result. Uses the step 1 builtin marker. Named test:
   the A and G blocks.
5. Trait conformance (groups H, I, J, L) and candidate selection (group K). Named test: the H-L blocks.
6. Source-less rendering (synthetic signatures). Needed for every `# note - synthetic
   signature` line. Requires either a precompile step that stores declaration signatures, or
   rendering from the AST cache. Decide this at step 6 with a measurement of the AST cache
   size. Named test: the whole test file, run under FileCheck with the source deleted.
7. Implicit-conversion deprecation (group D). Named test: the D block.

**Acceptance driver (to write in step 2 as a test, not as a tool).** Copy `diags_package/` and
`diagnostics_in_missing_locs.mojo` into a temporary directory, run the compiler on the copy with
`2>&1`, pipe into `/opt/homebrew/opt/llvm/bin/FileCheck <original test file>`, and require a nonzero
exit from the compiler (the RUN line uses `not`). A block-by-block run is `FileCheck --check-prefix`-free
and reports the first mismatching block, so each step above can be checked one group at a time.

**Scope note.** Parts 2 to 5 of this bug are on master and cover other test files. Step 2 is the only
piece that touches them. Step 1 changes decorator handling for every file, so it needs the stdlib
compile check described in CLAUDE.md before it is committed.

**Not landed this round.** No code change. This round's output is the measurement and the plan above.

### 2026-11-14: group B landed (overload failure), step 1 already done

Re-measured first: plan step 1 (decorator acceptance) was already in the tree
(`implicit` is in `_COMPILE_TIME_DECORATORS`; `import diags_package` runs).

Landed (`myinterpreter.py`, test `test_overload_diagnostic.py`, 4 cases):
- A call no overload accepts now prints the modular block instead of a one-line
  runtime TypeError: `error: no matching function in call to 'f'` with the
  call-site snippet, then one `note: candidate not viable: <reason>` per
  candidate with that candidate's `def` line and caret, and `Imported from
  <file>:<line>:` before a candidate declared in another file. Byte-identical to
  `tools/mojo build` for: zero-arg call over three overloads, too-many-args
  (caret on the callee), and candidates in an imported package. Block B of this
  test's CHECK lines is satisfied when the package source is still on disk.
- Mechanism: `overload_rejection`, `overload_diagnostic_record`,
  `_render_record_text`, hooked into `mojo_diagnostic` through an exception's
  `mojo_record`; `_FUNC_DEF_LOCS` records each def's file/line.
- Only the two reason kinds measured against the real compiler are rendered
  (missing required argument; unexpected argument), and only when every
  candidate has the same kind. Anything else keeps the old one-line error
  rather than a guessed block.

Still missing: groups A, C, D, E, F, G, H, I, J, K, L from the table above;
JSON output for the overload record; synthetic-signature rendering for a
source-less (precompiled) package, so the "source deleted" RUN line is still
unmet; mixed-reason overload sets; method overload sets (their defs are not
recorded in `_FUNC_DEF_LOCS`). This doc stays open for those.

### 2026-11-14 (later): group A landed (violated `where` clause), source-bearing

`def f[n: Int]() where n > 0` called as `f[0]()` is now rejected in the modular
shape (`error: invalid call to 'f': violated constraint`, `note: constraint
declared here evaluated to False, expected '(n > Int(0))'`, `note: function
declared here`), byte-identical to `tools/mojo build` for a same-file function
and for a package member (`pk.fc[0]()`, caret on the `.` with `~` either side,
`Imported from` lines). Test: `test_where_clause_diagnostic.py` (3 cases).

Mechanism (`myinterpreter.py`): `execute_FunctionDef` records functions with a
`where_clause` in `_FUNC_WHERE`; `MojoFunction._invoke` calls
`check_where_clause` once the comptime parameters are bound; a clause that
evaluates to exactly `False` raises `_ConstraintViolation` carrying a
`mojo_record` rendered by `_render_record_text`. `eval_CallExpr` publishes the
call site in `_CALL_SITE`. A clause the interpreter cannot decide (unbound
parameter, message tuple, evaluation error) is left alone, never reported.

Still missing for group A / this doc: the `$0`-style pretty-print the test's
precompiled form expects (needs the source-less path, plan step 6); `where`
clauses on struct declarations and `comptime _ = pkg.constraint_fn[0, 1]`
(group G); constraint expressions beyond identifiers, int literals and binary
operators; the compiled path's own (already existing) ConformanceError output
is a different format and is not unified with this one. Groups C-F, H-L remain.

### 2026-11-14 (later still): group J landed for same-module traits; static pass exists

`static_module_diagnostics` (`myinterpreter.py`, called from `fire.py`'s run
path before execution) is the first STATIC diagnostic pass: it reports, in
source order and all of them, a struct that names a trait of the same module as
a base but does not implement a required function (body `...`):
`'S' does not implement all requirements for 'T'`, a `required function 'f' is
not implemented` note per missing function (declaration order), then `trait 'T'
declared here`; one error per trait in the base closure, bases first. Byte-
identical to `tools/mojo build` on three shapes (inherited requirement, direct,
two missing in one trait, a default method in the trait is not required).
Test: `test_trait_requirements_diagnostic.py`.

Not covered: traits imported from another module (the test's own `diags_package`
case), `where`-conditional trait conformances, generic bases, JSON output.
Next groups on the same pass: H (parameter name conflict), I (conflicting
default implementations), L (comptime members), K (candidate selection).
Separate gap seen while testing, not this bug: the interpreter does not give a
struct the DEFAULT methods of its trait (`S().extra()` raises AttributeError).
