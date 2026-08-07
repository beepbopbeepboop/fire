# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status (updated 2026-08-07): ROOT CAUSE FIXED for link-mode's `_exports()`/`_parsed_import` sibling-file resolution — but NEITHER confirmed instance actually reaches PASS, both hit independent, deeper, unrelated bugs further into their transitive closure

Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_importlib_resources__common.md` and
`bugs/COMPILE_FAIL_Lib_runpy_request_for_member_module_in_something_not_a_structure_or_union.md`
(two independent files, same mechanism). Originally left unattempted as
cross-module import-resolution machinery with plausibly wide reach.

Re-investigated 2026-08-07 and the actual root cause turned out to be
narrower and more mechanical than the original "scan doesn't walk
function bodies" hypothesis (see "Corrected root cause" below — the
scan already DOES walk function bodies; the real bug is a step
downstream of that). Fixed the narrow, well-isolated part: link mode's
`_parsed_import`/`_exports()` had no way to locate a plain sibling `.py`
file (absolute bare name like `pkgutil`, or a leading-dot relative
import like `._adapters`) sitting next to the file currently being
compiled — both are outside this project's own std/test module
namespaces, which is all `imports.resolve_source`/
`_resolve_test_relative_module` know how to resolve. Without a source
path, `_register_link_imports` never found a real signature for the
imported name, so `_func_mangleable`/`_func_qualifier` treated it as
"never resolved" and the call site emitted a bare, unqualified name —
while `do_imports=True`'s SEPARATE inline pipeline (reached only via
mojo.py's link-mode-then-inline-fallback chain) resolves the very same
sibling file fine via `_compile_imported_module`'s own importer-
directory search, and DOES module-qualify the definition it inlines —
hence the mismatch and the undefined symbol at link time.

**Important honest caveat**: fixing this narrow resolution gap does
NOT make either of the two confirmed real-world instances reach a
successful `mojo.py build`. Both files have their OWN, separate,
unrelated COMPILE_FAIL bugs further into the now-successfully-resolved
transitive closure (see "Verification" below for exactly what each one
now hits instead). This fix is still being kept because (a) it is a
genuine, narrow, correctly-isolated bug fix verified clean against the
full 5-step quality gate with zero regression, (b) it removes a
systematically-wrong behavior (silently emitting a WRONG unqualified
extern for any function-scoped/relative import link mode can't
resolve) that could affect files outside this specific corpus, and (c)
per this session's own instructions, a value-adding fix is kept even
without a P/F flip on the two known instances, as long as it's verified
safe.

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

## Corrected root cause (2026-08-07 — supersedes the "partial" theory above)

The original hypothesis ("the cross-module import scan only walks
top-level statements, not function bodies") was WRONG. Link mode's
actual pre-pass, `_register_link_imports` (`gimple_codegen.py`), already
has a `scan()` helper that explicitly recurses into `FunctionDef`/
`IfStmt`/`WhileStmt`/`ForStmt`/`TryStmt` bodies looking for
`FromImportStmt` nodes — it finds `from pkgutil import read_code`/
`from ._adapters import wrap_spec` just fine, at exactly the depth
these two examples live at. The `_import_scope_stack` lexical-scope
mechanism (`_push_import_scope`/`_gen_stmt_FromImportStmt`) that
resolves a function-scoped import's qualifier for `_func_qualifier`'s
"scopes" tier is also already correctly wired.

The REAL gap is one step earlier: `_register_link_imports.scan()` calls
a local `_exports(module)` helper to resolve the imported module's
signature — first via `imports.resolve(module)` (a real dylib), then
falling back to `self._parsed_import(module)` + `load_module(module)`
(source-level text extraction) for a module with no dylib.
`_parsed_import` (`gimple_codegen.py`) only ever tried
`imports.resolve_source(module)` and `self._resolve_test_relative_module
(module)` — BOTH scoped to this project's own std/test module
namespaces (confirmed directly: `module_loader.resolve_module_path
('pkgutil')` raises `ValueError: Only stdlib and test imports
supported: pkgutil`). Neither has any notion of "a plain sibling `.py`
file next to the file currently being compiled" (the `pkgutil` case)
NOR "a leading-dot relative import" (the `._adapters` case) — both very
ordinary shapes for an arbitrary external multi-file Python project
(exactly what compiling the real Python-3.14.6 stdlib is).
`do_imports=True`'s SEPARATE inline pipeline (`_compile_imported_module`)
already resolves both shapes correctly via its own importer-directory
search — but link mode's `_parsed_import`/`_exports` never shared that
logic.

With no resolvable path, `_exports` returns `({}, False, None)`;
`_register_link_imports.scan()`'s "not info" branch (which tries to
read the module's OWN source text to detect a generic/inline-fallback
case) has no `source` to read either, so NOTHING gets registered:
`sym` is never added to `_mangled_funcs`, `_own_imported_func_home`
never learns `read_code -> pkgutil`, and `_link_inline_modules` never
gets `pkgutil` queued for the "compile this whole module inline, no
dylib available" fallback. The ONLY registration `read_code` ever gets
is from `_gen_stmt_FromImportStmt` when the function BODY is later
compiled (a real statement in that body too) — which stores
`self.imported_symbols['read_code'] = {'module': 'pkgutil',
'return_type': 'int64_t'}`, deliberately WITHOUT a `'signature'` key
(see that method's own comment: the fallback default exists so an
unresolvable import's call site still lowers to SOME type rather than
crashing). The FINAL extern-emission pass (`gen_module`'s "Extern
declarations: imported symbols with full parameter information"
block) takes the "no signature was ever attached" branch for exactly
this shape and, for `link_imports=True`/`do_imports=False` (link
mode's own flags), falls into the "historical bare-extern behavior"
branch — `_func_mangleable('read_code')` is False (nothing marked it
mangled), so `_func_csym` returns the UNQUALIFIED name, and the extern
+ every call site agree on that same wrong, unqualified name. Meanwhile
`do_imports=True`'s inline pipeline (reached ONLY via mojo.py's
link-mode-then-inline-fallback chain, a completely different compile of
the SAME source) resolves `pkgutil` fine and inlines a `pkgutil_
read_code_<suffix>`-qualified definition — which is why the symptom is
specifically an undefined symbol at LINK time (the extern's shape is
internally self-consistent, it's just never actually defined anywhere
in what THIS pipeline links).

## Fix (2026-08-07)

Two additive changes, `gimple_codegen.py`:

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
   candidate that exists on disk. Reuses the exact same search-order
   logic `_compile_imported_module` already uses successfully instead
   of a second, parallel implementation (per this repo's own
   "consolidate duplicates" convention).

No change was needed to `_register_link_imports`, `_func_qualifier`, or
the extern-emission pass — once `_parsed_import` can find the real
source file, the EXISTING "not info -> read module source text ->
`_link_inline_modules.add(...)`" fallback branch (already correct) and
the EXISTING `_own_imported_func_home`/scope-stack-derived qualifier
machinery (already correct) both just start working for these two
shapes, exactly as they already did for every OTHER resolvable import.

## Verification

Full 5-step quality gate, all clean:
1. `test_gimple.py`: 247/247 passed.
2. `test_module_cache.py`: 76/76 passed.
3. `make check-selfhost`: clean (mojo.py compiling itself, 1/1 passed).
4. From-scratch stdlib dylib rebuild
   (`rm -f build/libmojostdlib.dylib` + `build_stdlib_dylib.build_stdlib
   (jobs=8)`): 0 `skip <module>:` lines.
5. `compile_stdlib.py -j8`: **664/664 passed, 0 unexpected** (same as
   baseline before this fix — no regression, no improvement; this
   fallback path is essentially never exercised by this project's own
   `std.*` modules, which almost always resolve via a real dylib).

Direct confirmation the fix does what it says (`gimple_codegen.
compile_linked()` invoked directly, inspecting the generated C):
- `Lib/runpy.py`: `read_code`/`get_importer` call sites and their
  externs both now read `pkgutil_read_code_<suffix>`/
  `pkgutil_get_importer_<suffix>` (previously bare `read_code`/
  `get_importer`) — pkgutil.py's body is now correctly inlined via the
  `_link_inline_modules` fallback.
- `Lib/importlib/resources/_common.py`: `wrap_spec` call site and its
  extern both now read `__adapters_wrap_spec_<suffix>` (previously bare
  `wrap_spec`) — `_adapters.py`'s body (including its
  `SpecLoaderAdapter`/`TraversableResourcesLoader`/`CompatibilityFiles`
  classes) is now correctly inlined.

**Neither file reaches a successful `mojo.py build`, though — both
have separate, unrelated, deeper bugs now reachable in the newly-
resolved transitive closure**:
- `Lib/runpy.py` now compiles much further (no more `link failed` for
  `read_code`/`get_importer`) but the client.c compile itself now hits
  independent GIMPLE-type errors from OTHER transitively-imported
  stdlib files pulled in along the way (`Lib/stat.py`'s `int64_t & char
  *`, `Lib/posixpath.py`'s `expandvars_repl_env` struct-shape mismatch,
  `Lib/operator.py`'s `__matmul__`, `Lib/dis.py`'s `void`-declared
  variable, `Lib/enum.py`'s gimple-call conversion) — all pre-existing,
  unrelated bugs, most already independently filed. Since
  `driver.compile_program`'s failures are caught by `mojo.py`'s own
  try/except and fall back to `build_executable` (the OLDER, separate
  inline pipeline), and THAT pipeline was already failing on
  essentially the same transitive-closure bugs before this fix too, the
  file's overall `mojo.py build` categorization is unchanged (still not
  PASS) — this fix only changes WHERE in the pipeline link mode itself
  gives up before falling back, not the final outcome.
- `Lib/importlib/resources/_common.py` now hits a DIFFERENT bug:
  `Lib/importlib/_abc.py` (module `_abc`) and `Lib/importlib/abc.py`
  (module `abc`) both get inlined into the same translation unit (both
  transitively reachable once `_adapters.py` itself is correctly
  resolved) and their globals structs collide (`redefinition of
  '___abc_globals'`) — this is the SAME class of bug as the explicitly
  out-of-scope `bugs/hard/CODEGEN_same_bare_name_struct_collision_
  across_modules.md` (task #141) / `bugs/hard/CODEGEN_cross_module_
  bare_import_name_collision.md`, both deliberately not attempted this
  session per the orchestrating session's explicit instructions. Not
  chased further here for the same reason.

## Risk assessment (post-fix)

Confirmed LOW in practice, despite touching cross-module import
resolution (a category this session otherwise treats as high-risk):
the change is purely ADDITIVE (a new fallback tier, only ever consulted
when BOTH pre-existing resolvers already returned nothing — it can only
turn a previously-"never resolved" case into a resolved one, never
change the answer for anything that already resolved via an existing
tier) and the full 5-step gate, including the load-bearing `compile_
stdlib.py -j8` regression check, came back with the EXACT same 664/664
result as baseline. Kept despite not flipping either known instance to
PASS, per this task's own guidance that a correctly-verified fix with
real (if not immediately visible) value is worth keeping.
