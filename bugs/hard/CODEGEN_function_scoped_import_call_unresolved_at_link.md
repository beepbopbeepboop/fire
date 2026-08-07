# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status (updated 2026-08-07): Root cause fully understood; a fix was implemented, verified against all 5 mandated gates clean, then REVERTED after independently discovering it regresses a THIRD, previously-passing file not covered by any of those 5 gates. NOT shipped. Still unfixed.

Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_importlib_resources__common.md` and
`bugs/COMPILE_FAIL_Lib_runpy_request_for_member_module_in_something_not_a_structure_or_union.md`
(two independent files, same mechanism). Originally left unattempted as
cross-module import-resolution machinery with plausibly wide reach.

Re-investigated 2026-08-07: the original "scan doesn't walk function
bodies" hypothesis was WRONG (see "Corrected root cause" below — the
scan already walks function bodies fine; the real gap is one step
earlier, in path resolution). A fix was implemented (see "Fix
implemented, then reverted" below), and it correctly did what it was
supposed to do — confirmed via direct C-output inspection for both
known instances. It also passed the full mandated 5-step quality gate
completely clean (test_gimple.py 247/247, test_module_cache.py 76/76,
check-selfhost clean, from-scratch dylib rebuild 0 skips, compile_
stdlib.py -j8 664/664 0 unexpected — byte-identical to baseline).

**But it was reverted anyway**, for two compounding reasons discovered
only after the gate passed clean:
1. Neither of the two ORIGINAL confirmed instances (`runpy.py`,
   `importlib/resources/_common.py`) actually reaches a passing
   `mojo.py build` even with the fix — both have separate, unrelated,
   deeper bugs newly reachable once their transitive closure resolves
   correctly (see "What the fix actually achieves" below). Zero
   observed P/F flips.
2. Independently spot-checking OTHER already-passing COMPILE_FAIL docs
   (routine practice, not triggered by any specific suspicion) found
   that the fix **regresses `Lib/importlib/__init__.py` from a clean
   PASS to a hard COMPILE_FAIL** — a file with NO known connection to
   this bug, not touched by any of the fix's own testing. Root cause:
   `importlib/__init__.py` does `from . import _bootstrap`, and the
   SAME fix that correctly resolves `pkgutil`/`._adapters` ALSO now
   resolves `_bootstrap.py` (previously silently unresolved and never
   inlined at all) — but `_bootstrap.py` itself has its own pre-
   existing, unrelated GIMPLE-type bug (`non-trivial conversion in
   'integer_cst'` at line 393, a `char* -> int64_t` pointer/integer
   mismatch at line 951) that was never reachable before because
   `_bootstrap.py` was never actually compiled as part of this file's
   closure. Confirmed via a direct before/after comparison (`git apply
   -R`/`git apply` round-trip on the exact same fix patch): WITHOUT the
   fix, `mojo.py build Lib/importlib/__init__.py` → rc=0, real `.o`
   produced. WITH the fix, same command → rc=1, no `.o`, the
   `_bootstrap.py` errors above.

**None of the 5 mandated gates caught this** — `compile_stdlib.py`
tests this project's own `std.*` Mojo modules (which resolve via real
dylibs, never hitting this specific source-level fallback path),
`check-selfhost` tests this compiler's own Python source (single-file,
no sibling/relative multi-file imports of this shape), and
`test_gimple.py`/`test_module_cache.py` are unit-level. The actual
regression only showed up against the Python-3.14.6 COMPILE_FAIL
corpus this task exists to improve — which is exactly why this task's
own instructions call for re-verifying against the corpus itself, not
just the prescribed gate, before calling anything done. Recorded here
as a concrete instance of that principle, alongside this project's
other two documented "passed compile_stdlib.py cleanly but still
regressed something" incidents.

**Conclusion**: this specific narrow fix is not viable as-is — its
value (correctly resolving two more import shapes) is real, but its
side effect (newly resolving OTHER previously-silently-unresolved
sibling/relative imports across the ENTIRE Python-3.14.6 corpus, each
of which may have its own independent, latent, never-before-reachable
bug) makes its blast radius fundamentally larger than "two known
files," and untestable in full without exhaustively re-running the
ENTIRE corpus (60+ files, not just the 2 originally-confirmed
instances) for every candidate fix — which is what actually caught
this. Left unfixed. A future attempt should re-run the full COMPILE_FAIL
corpus triage (not just the specific instances motivating the fix)
before considering any fix here landable, precisely because this
resolution path is shared by every unresolved sibling/relative import
in the whole corpus, not just the 1-2 files that happen to demonstrate
the symptom.

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

## Fix implemented, verified, then REVERTED (2026-08-07) — kept here for whoever attempts this next

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

This fix (both changes above) was applied, committed, then fully
REVERTED (`git apply -R` of the exact same patch) once the
`importlib/__init__.py` regression below was found — it does NOT exist
in the current tree. Described here in full so a future attempt
doesn't have to re-derive it from scratch, but it should not be
re-applied verbatim without ALSO solving the "silently-unresolved
sibling import may hide an unrelated latent bug" problem described in
the Status section above (e.g. by only inlining the resolved sibling
module when a fast up-front syntax-only check shows it wouldn't hit a
KNOWN class of GIMPLE-type error, or by making the newly-resolved
inline-fallback path fail soft — falling back to the OLD "unresolved,
stub it out" behavior — when the sibling module itself doesn't compile
clean, rather than propagating its error up through the whole client
build).

## Verification (of the reverted fix, before it was reverted)

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

## Risk assessment (revised, post-revert) — the "purely additive, so it's safe" reasoning was insufficient

The fix genuinely IS purely additive at the CODE level (a new fallback
tier, only ever consulted when both pre-existing resolvers already
returned nothing — it literally cannot change the answer for anything
that already resolved via an existing tier), and the full 5-step gate
came back byte-identical to baseline (664/664). Both of those are true
and were not wrong. What was wrong was treating "purely additive at
the code level" as equivalent to "safe" — being ADDITIVE only bounds
what happens to imports that ALREADY resolved; it says nothing about
what happens to the (potentially large) set of imports that used to
resolve to NOTHING and now resolve to a REAL file with its own
independent, previously-unreachable bugs. That set is exactly the
"function-scoped or relative sibling import this compiler couldn't
previously find" set — which, for a corpus the size of the full
Python-3.14.6 stdlib/tools tree, is not a small, easily-enumerable set
at all. The `importlib/__init__.py` regression is a direct instance of
exactly this: previously-silent non-resolution accidentally acting as
a firewall against `_bootstrap.py`'s own bug.

Lesson for next time: for a fix whose whole nature is "resolve
something that used to be unresolved," the load-bearing check is NOT
"does the mandated 5-gate stay green" (necessary but insufficient) —
it's "does the FULL COMPILE_FAIL corpus's pass count stay the same or
improve," run before AND after, over the WHOLE corpus, not just the
files that motivated the fix. That full-corpus re-triage is what
actually caught this regression, well after the mandated gate had
already passed clean.
