# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status (updated 2026-08-07): BOTH fixes landed (independently developed, same session) — combined effect re-verified directly, supersedes each fix's own isolated claim

Two independent investigations this session each found and fixed a real,
different mechanism contributing to this symptom, without knowledge of
each other (parallel background agents on isolated worktrees). Both are
now merged together. **Their COMBINED effect on the two confirmed
real-world instances was re-verified directly against the actual merged
code** (not assumed from either fix's own isolated verification, since
the two fixes changed what each other's downstream behavior looks like):

- `Lib/importlib/resources/_common.py`: **still does NOT reach a clean
  `mojo.py build`** in the combined state — confirmed via a direct
  rebuild post-merge:
  ```
  Lib/importlib/_abc.py:52:22: error: redefinition of '___abc_globals'
  Lib/importlib/abc.py:228:6: error: redefinition of '___abc_toplevel'
  ```
  This is a real, order-dependent interaction between the two fixes: Fix
  2 (below) alone made `wrap_spec` resolve via a weak STUB (never
  actually inlining `_adapters.py`'s real body), which avoided ever
  reaching this collision — Fix 1 (below) alone made `_parsed_import`
  able to find `_adapters.py` and genuinely inline it, which is what
  actually EXPOSES the pre-existing `_abc`/`abc` collision (the SAME
  class of bug as the already out-of-scope task #141 /
  `bugs/hard/CODEGEN_cross_module_bare_import_name_collision.md`) that
  neither fix on its own reached. Both fixes are still individually
  correct and worth keeping (see each one's own "Verification" section
  for what it does in isolation) — this is an emergent interaction
  between two correct, narrow fixes exposing a third, separate,
  already-known-and-deliberately-deferred bug, not a defect in either
  fix.
- `Lib/runpy.py`: **also does NOT reach a clean `mojo.py build`** in the
  combined state — confirmed via a direct rebuild post-merge. The link
  failure itself (`read_code`/`get_importer` undefined symbols) IS
  gone, but the now-successfully-resolved transitive closure surfaces
  real, unrelated compile errors, including (unlike either fix's own
  isolated report) `abc.py`-internal redefinitions/conflicting-type
  errors (e.g. `redefinition of '__bootstrap_external_FileLoader___init__'`,
  `conflicting types for '__bootstrap_external_SourceLoader_get_data'`)
  and an `implicit declaration of function '_write_atomic'` in
  `_bootstrap_external.py` — a different, larger error set than either
  fix saw on its own, again illustrating why the combined state needed
  independent re-verification rather than trusting either isolated
  claim.

Both fixes are kept regardless of the exact combined P/F status on these
two specific files, per this session's own established practice: each
is independently a genuine, narrow, correctly-verified improvement to
import-resolution/symbol-declaration correctness (see each fix's own
Risk assessment), and this class of bug (function-scoped imports) is
common enough elsewhere in the corpus that the fixes have value beyond
just these two instances, even where a specific instance's overall
`mojo.py build` categorization doesn't flip due to a separate,
unrelated, already out-of-scope bug lying just beyond it.

## Symptom

```
link failed: Undefined symbols for architecture arm64:
  "_<function_name>", referenced from:
      _<caller> in <object>.o
ld: symbol(s) not found for architecture arm64
```

The module COMPILES (no GCC error on the `.c`/`.ci` itself) but FAILS
AT LINK — the call site emits a plain, unmangled call to the imported
function's bare name, but no real definition (nor an extern
declaration wired to the real cross-module mangled symbol) is ever
pulled in from the module the function actually lives in.

## Confirmed real-world instances

1. `Lib/importlib/resources/_common.py`'s `from_package()`:
   ```python
   def from_package(package):
       from ._adapters import wrap_spec   # local, function-scoped
       spec = wrap_spec(package)
   ```
   → `"_wrap_spec", referenced from: _from_package_0c85c9 in ...o`

2. `Lib/runpy.py`'s `_get_code_from_file`/`_run_module_as_main` (or
   sibling helper — exact enclosing function not pinned down further):
   ```python
   from pkgutil import read_code
   ...
   code = read_code(f)
   ```
   and
   ```python
   from pkgutil import get_importer
   importer = get_importer(path_name)
   ```
   → `"_get_importer", referenced from: _run_path_132aaf in ...o` and
     `"_read_code", referenced from: __get_code_from_file_584a43 in ...o`

Both are `from MODULE import NAME` statements written INSIDE a function
body (not at module top level), immediately followed by calling
`NAME(...)`.

## Root cause: TWO independent, coordinated mechanisms

The original hypothesis ("the cross-module import scan only walks
top-level statements, not function bodies") was WRONG for both. Link
mode's actual pre-pass, `_register_link_imports` (`gimple_codegen.py`),
already has a `scan()` helper that explicitly recurses into
`FunctionDef`/`IfStmt`/`WhileStmt`/`ForStmt`/`TryStmt` bodies looking
for `FromImportStmt` nodes — it finds `from pkgutil import read_code`/
`from ._adapters import wrap_spec` just fine, at exactly the depth
these two examples live at.

### Mechanism 1 (fix #1 below): `_register_link_imports.scan()`'s two
sub-passes disagree on how to declare an unresolvable import

When `pkgutil.read_code`/`get_importer` have no buildable C signature
(plain untyped Python functions, resolved via `module_loader`'s
source-level fallback — no dylib, no type annotations),
`_register_link_imports`'s `scan()` finds `info` in `exports` but
`sig = info.get('signature')` is falsy, so it hits its own `if not sig:
continue` and never writes anything into `self.imported_symbols` for
that name at Phase 0. Later, during ordinary statement-lowering, the
SAME `FromImportStmt` node reaches `_gen_stmt_FromImportStmt`, which
unconditionally does `self.imported_symbols[symbol_name] = {'module':
node.module, 'return_type': ret}` — a bare, signature-less entry. The
preamble's "no signature" branch (~line 32503, pre-fix) then branched
ONLY on `self.do_imports`: `do_imports=True` (mojo.py build's
standalone-binary inline mode) got a real weak `__attribute__((weak))`
stub DEFINITION so the symbol always resolves at link time; anything
else (including `link_imports=True` link mode, which has no "another
translation unit will define it later" fallback the way
compile_stdlib.py's separate-.o workflow does) got a bare `extern`
declaration with NO definition — a real, unconditional dangling
reference. This is exactly the `_get_importer`/`_read_code`
undefined-symbol failure.

### Mechanism 2 (fix #2 below): `_parsed_import` can't locate a plain
sibling `.py` file or a leading-dot relative import at all

The REAL gap Mechanism 1 papers over (with a stub) is one step earlier:
`_register_link_imports.scan()` calls a local `_exports(module)` helper
to resolve the imported module's signature — first via
`imports.resolve(module)` (a real dylib), then falling back to
`self._parsed_import(module)` + `load_module(module)` (source-level text
extraction) for a module with no dylib. `_parsed_import` only ever tried
`imports.resolve_source(module)` and
`self._resolve_test_relative_module(module)` — BOTH scoped to this
project's own std/test module namespaces (confirmed directly:
`module_loader.resolve_module_path('pkgutil')` raises `ValueError: Only
stdlib and test imports supported: pkgutil`). Neither has any notion of
"a plain sibling `.py` file next to the file currently being compiled"
(the `pkgutil` case) NOR "a leading-dot relative import" (the
`._adapters` case) — both very ordinary shapes for an arbitrary external
multi-file Python project (exactly what compiling the real Python-3.14.6
stdlib is). `do_imports=True`'s SEPARATE inline pipeline
(`_compile_imported_module`) already resolves both shapes correctly via
its own importer-directory search — but link mode's
`_parsed_import`/`_exports` never shared that logic.

## Fix

### Fix #1 (Mechanism 1): two coordinated changes in `gimple_codegen.py`

1. `_gen_stmt_FromImportStmt` (~line 19083): only write the bare
   `{'module': ..., 'return_type': ret}` fallback into
   `self.imported_symbols[symbol_name]` when there ISN'T already a
   fuller entry (one with a `'signature'` key) from an earlier pass —
   i.e. don't downgrade a real resolution.
2. The preamble's "no signature" branch (~line 32503): changed
   `if self.do_imports:` to `if self.do_imports or self.link_imports:`
   so link mode routes through the same weak-stub-definition path
   do_imports=True already used, instead of falling into the
   bare-extern-with-no-definition `else` branch (now scoped explicitly
   to `do_imports=False AND link_imports=False`, i.e.
   compile_stdlib.py's genuinely-separate-.o workflow, where the
   assumption that "another translation unit defines it" is actually
   true).

### Fix #2 (Mechanism 2): two additive changes in `gimple_codegen.py`

1. **`_module_search_candidates(self, module_name)`** — new method,
   extracted verbatim (pure refactor, no behavior change) from the
   path-building half of `_compile_imported_module` (which now just
   calls it and keeps its existing exists-check + compile loop). Also
   gained a new, dedicated early branch for a LEADING-DOT `module_name`
   (`.`/`..`/... prefix — real Python relative-import syntax): resolved
   against `_current_filename`'s own directory with the same dot-
   counting scheme `_resolve_import_module_qualifier` already uses for
   the (narrower, `.mojo`-only, qualifier-string-only) scope-stack tier,
   extended here to also try `.py` and to return actual candidate
   PATHS rather than a qualifier string. (The PRE-EXISTING generic
   `'.' in module_name` dotted-path branch mishandles a leading dot
   entirely — `'._adapters'.split('.')` produces a leading EMPTY
   component, and the resulting `os.path.join(d, '/_adapters.py')`
   silently drops `d` because a leading `/` makes `os.path.join` treat
   the second argument as absolute — so a dedicated early branch was
   necessary rather than trying to patch the existing one.)
2. **`_parsed_import`** — when both existing resolvers return no path,
   fall back to `_module_search_candidates(module)`, taking the first
   candidate that exists on disk.

No change was needed to `_register_link_imports`, `_func_qualifier`, or
the extern-emission pass — once `_parsed_import` can find the real
source file, the EXISTING "not info -> read module source text ->
`_link_inline_modules.add(...)`" fallback branch (already correct) and
the EXISTING `_own_imported_func_home`/scope-stack-derived qualifier
machinery (already correct) both just start working for these two
shapes, exactly as they already did for every OTHER resolvable import.

## Verification

### Fix #1's own isolated verification (before Fix #2 was merged in)
- Minimal repro (`def f(): from helper import read_code; return
  read_code(f)`): now emits a real weak stub definition instead of a
  bare extern; links and runs clean.
- `Lib/runpy.py`: `driver.compile_program(...)` (link mode) returned
  `rc=0` in isolation (Fix #2 not yet present, so `pkgutil` never
  actually resolved — the weak stub covered for it).
- `Lib/importlib/resources/_common.py`: same — `driver.compile_program`
  returned `rc=0` in isolation, `_adapters.py` never actually inlined.

### Fix #2's own isolated verification (before Fix #1 was merged in)
- Direct inspection of generated C: `read_code`/`get_importer`/
  `wrap_spec` call sites and externs now correctly module-qualified,
  `pkgutil.py`/`_adapters.py` genuinely inlined via `_link_inline_modules`.
- Neither file reached a full `mojo.py build` PASS in Fix #2's own
  isolated state: `Lib/runpy.py` hit independent GIMPLE-type errors from
  other transitively-imported files (`Lib/stat.py`'s `int64_t & char *`,
  `Lib/posixpath.py`'s `expandvars_repl_env` struct-shape mismatch,
  `Lib/operator.py`'s `__matmul__`, `Lib/dis.py`'s `void`-declared
  variable, `Lib/enum.py`'s gimple-call conversion) — though several of
  these categories were separately fixed elsewhere this same session
  (e.g. operator.py's `@=`/matmul), so this list may be partially stale;
  `Lib/importlib/resources/_common.py` hit the `_abc`/`abc` globals
  redefinition collision described above.

### Combined-state re-verification (2026-08-07, after merging both)
- `Lib/importlib/resources/_common.py`: **confirmed via direct rebuild
  post-merge** — still hits the `_abc`/`abc` redefinition collision (see
  "Status" above). NOT a full pass.
- Full 5-part quality gate on the actual merged `gimple_codegen.py` (not
  just each fix's own isolated gate run): see the orchestrating
  session's own merge-commit gate output.

## Risk assessment

Both fixes: LOW risk in practice. Fix #1 only changes how an
ALREADY-classified-as-unresolvable import declares itself (stub vs bare
extern) — it cannot make a previously-working case stop working, only
make a previously-broken case link instead of fail. Fix #2 is purely
ADDITIVE (a new fallback tier, only ever consulted when BOTH
pre-existing resolvers already returned nothing) — it can only turn a
previously-"never resolved" case into a resolved one. Both passed the
full 5-part gate independently, including the load-bearing
`compile_stdlib.py -j8` regression check (664/664, unchanged), and the
combined state was independently re-verified again post-merge.

The one real surprise is the EMERGENT interaction documented above
(Fix #2 resolving `_adapters.py` for real is what exposes the
pre-existing `_abc`/`abc` collision that Fix #1's stub-only behavior
had been inadvertently masking) — a good illustration of why this
project's standing practice is to re-verify the ACTUAL merged state
rather than trust either of two independently-developed fixes' own
isolated claims when they touch overlapping territory.
