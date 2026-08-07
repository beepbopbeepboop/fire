# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status

Unfixed. Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_importlib_resources__common.md` and
`bugs/COMPILE_FAIL_Lib_runpy_request_for_member_module_in_something_not_a_structure_or_union.md`
(two independent files, same mechanism). Not attempted — this is
cross-module import-resolution machinery, and function-scoped imports
are a common, deliberate Python idiom (deferred/circular-import
avoidance), so a fix plausibly has wide reach across the stdlib corpus
this compiler targets.

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

## Root cause (partial)

Not fully traced into the exact codegen call site (out of scope for
this investigation's remaining time budget), but the shape is
consistent across both instances: this codegen's cross-module import
resolution (whatever wires up `from X import Y` to Y's real, mangled
C symbol + an `extern` forward declaration) appears to run as a
TOP-LEVEL-statement pre-pass — top-level `from X import Y` at module
scope gets a real resolved reference, but the SAME statement written
inside a function body does not get the same treatment: the call site
`Y(...)` still emits (correctly resolves the NAME to a call
expression), but nothing registers `Y` as "needs an extern decl + the
real mangled symbol from module X" for the LINKER's sake — so the
unmangled bare name goes into the object file with no definition
anywhere, only caught by the linker, not the compiler.

## What a real fix needs

1. Find wherever this codegen scans `from X import Y` for cross-module
   symbol wiring (likely a pre-pass similar to `_register_link_imports`
   / `_emit_stdlib_import_externs`, given their names elsewhere in
   `gimple_codegen.py`) and confirm it only walks TOP-LEVEL statements,
   not function bodies.
2. Extend that scan to also walk (or be re-invoked for) `FromImportStmt`
   nodes found inside function/method bodies via the existing
   `_walk_ast` generic traversal (the same tool several other fixes
   this session used for exactly this "also look inside nested bodies"
   class of gap).
3. Verify against BOTH confirmed instances above plus a fresh minimal
   repro (`def f(): from some_module import helper; return helper()`)
   — a real fix should make the call site route through the same
   symbol-resolution path a top-level import already gets, not require
   inventing new machinery.
4. Full quality gate — cross-module import wiring is used broadly
   enough (any local/deferred import anywhere in the stdlib) that a
   change here needs the full 5-step verification, particularly the
   from-scratch stdlib dylib rebuild's skip-count check.

## Risk

Moderate — narrower than the type-inference-machinery bugs elsewhere in
this session (this is specifically about import/symbol WIRING, not
value type inference), but the fix touches a pre-pass that presumably
runs once per module and whose exact current scope (top-level-only)
was never explicitly investigated — could plausibly have surprising
interactions with existing top-level import handling if merged
carelessly rather than added as a clearly-separate pass. Not attempted
this session.
