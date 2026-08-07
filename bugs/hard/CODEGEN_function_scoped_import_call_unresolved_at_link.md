# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status (FIXED 2026-08-07, Track B continuation session)

Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_importlib_resources__common.md` and
`bugs/COMPILE_FAIL_Lib_runpy_request_for_member_module_in_something_not_a_structure_or_union.md`
(two independent files, same mechanism). Fixed 2026-08-07 in
`gimple_codegen.py` only, two coordinated changes — see "Root cause
(full)" and "Fix" below. Both confirmed real-world instances now build
AND link successfully via `driver.compile_program` (link mode):
`Lib/runpy.py` (7.0s, was a hard link failure) and
`Lib/importlib/resources/_common.py` (also incidentally fixed the
doc's own second, `next()`-builtin-shaped finding — see "Also fixed"
below).

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

## Root cause (full, 2026-08-07)

The original partial diagnosis ("the cross-module import scan only
walks top-level statements") turned out to be WRONG once actually
traced: `gen_module`'s link-mode Phase 0 pre-pass,
`_register_link_imports` (~gimple_codegen.py:4828), already DOES
recurse into function/method bodies (`elif isinstance(stmt,
FunctionDef): scan(stmt.body)`, plus `IfStmt`/`WhileStmt`/`ForStmt`/
`TryStmt`) — a function-scoped `from pkgutil import read_code` reached
via `_get_code_from_file`'s body IS found by this scan. The bug is a
completely different, downstream mechanism:

1. **A later pass silently overwrites the earlier pass's correct
   registration.** When `pkgutil.read_code`/`get_importer` have no
   buildable C signature (plain untyped Python functions, resolved via
   `module_loader`'s source-level fallback — no dylib, no type
   annotations), `_register_link_imports`'s `scan()` finds `info` in
   `exports` but `sig = info.get('signature')` is falsy, so it hits its
   own `if not sig: continue` and never writes anything into
   `self.imported_symbols` for that name at Phase 0. Later, during
   ordinary statement-lowering, the SAME `FromImportStmt` node (still
   physically present inside the function body — Phase 0 only READS
   it, doesn't remove it) reaches `_gen_stmt_FromImportStmt`
   (~line 19067), which unconditionally does `self.imported_symbols
   [symbol_name] = {'module': node.module, 'return_type': ret}` — a
   bare, signature-less entry. (For a TOP-LEVEL import this method is
   never even called — `gen_module`'s statement dispatch explicitly
   skips top-level `FromImportStmt`s, per that method's own
   docstring — so this only fires for function-scoped ones.)

2. **The preamble's "how do I declare this unresolved import" branch
   picks the WRONG strategy for link mode.** `gen_module`'s extern-decl
   preamble loop (~line 32382 onward) iterates `self.imported_symbols`
   and, for any entry with no `'signature'` key, used to branch
   ONLY on `self.do_imports` (~line 32505, pre-fix): `do_imports=True`
   (mojo.py build's standalone-binary inline mode) got a real weak
   `__attribute__((weak))` stub DEFINITION ("unavailable in compiled
   mode") so the symbol always resolves at link time even though it's
   functionally a no-op; anything else (`do_imports=False`, which is
   BOTH `link_imports=True` link mode AND compile_stdlib.py's
   genuinely-separate-.o workflow) got a bare `extern` declaration with
   NO definition, on the reasoning ("Keep the historical bare-extern
   behavior... an unresolved-here name may legitimately be defined in
   one of those other translation units") that's only true for
   compile_stdlib.py's sibling-.mojo-files-compiled-separately
   scenario, not for link mode's dylib-based imports — in link mode, if
   Phase 0's own dylib/reflection-aware scan already looked at this
   exact name and found no signature, there IS no "other translation
   unit" that will ever define it; the bare extern is a real,
   unconditional dangling reference. This is exactly the `_get_importer`
   /`_read_code` undefined-symbol failure.

   (Separately, a TOP-LEVEL import of the same kind of unresolvable
   name does NOT hit this dangling-extern branch at all: it never gets
   an `imported_symbols` entry in the first place — see point 1 — so
   at the CALL SITE it's `_lower_named_call`/`_gen_stmt_ExprStmt`'s own
   independent `_is_unknown`/`_is_unknown_stmt` auto-stub mechanism
   that recognizes the genuinely-unknown callee and emits its own weak
   stub right there. The function-scoped case never reaches that
   mechanism because `_gen_stmt_FromImportStmt`'s bare registration
   [point 1] already made the name look "known" by the time the call
   site is lowered.)

## Fix

Two coordinated changes in `gimple_codegen.py`, both minimal and
narrowly scoped:

1. `_gen_stmt_FromImportStmt` (~line 19083): only write the bare
   `{'module': ..., 'return_type': ret}` fallback into
   `self.imported_symbols[symbol_name]` when there ISN'T already a
   fuller entry (one with a `'signature'` key) from an earlier pass —
   i.e. don't downgrade a real resolution. (In practice this specific
   guard rarely fires by itself for the confirmed repros — Phase 0
   genuinely never resolved a signature for these names either — but
   it closes a real overwrite hazard for the case where Phase 0 DOES
   find a signature and body-lowering would otherwise clobber it, and
   is a correctness improvement independent of fix #2.)
2. The preamble's "no signature" branch (~line 32503): changed
   `if self.do_imports:` to `if self.do_imports or self.link_imports:`
   so link mode routes through the same weak-stub-definition path
   do_imports=True already used, instead of falling into the
   bare-extern-with-no-definition `else` branch. The `else` branch's
   own comment/reasoning was narrowed to make explicit it's now only
   correct for the genuinely-separate-.o compile_stdlib.py workflow
   (`do_imports=False AND link_imports=False`), not link mode.

## Verification

- Minimal repro (`def f(): from helper import read_code; return
  read_code(f)`, `helper.py` defining plain untyped `read_code`/
  `get_importer`): `gimple_codegen.compile_linked(...)` now emits a
  real `__attribute__((weak))` stub definition for both names instead
  of a bare extern; `mojo.py build` on the repro links and runs clean
  (previously: `ld: symbol(s) not found for architecture arm64`).
- `Lib/runpy.py`: `driver.compile_program(...)` (link mode) now
  returns `rc=0` — previously failed with `Undefined symbols ...
  "_get_importer"` / `"_read_code"`. Full `python3 mojo.py build
  Lib/runpy.py` also now succeeds end-to-end in ~7s.
- `Lib/importlib/resources/_common.py`: `driver.compile_program(...)`
  now also returns `rc=0` — this incidentally fixes the doc's OTHER,
  previously-undocumented-as-a-hard-bug finding too (`next(itertools.
  filterfalse(...))`'s `_next` undefined symbol — `next` turns out to
  reach `self.imported_symbols` via the exact same "no signature"
  preamble branch this fix touches, so it now gets the same weak stub).
  `python3 mojo.py build .../_common.py` also succeeds end-to-end.

## Quality gate (2026-08-07)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean (`1 passed, 0 failed`).
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib`
   + `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0
   `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures** (unchanged from baseline).

## Risk (pre-fix assessment, now resolved)

Moderate — narrower than the type-inference-machinery bugs elsewhere in
this session (this is specifically about import/symbol WIRING, not
value type inference). The actual fix ended up even narrower than the
original plan predicted (two small, independently-justified branch
conditions, no new pre-pass/traversal needed) — the original "extend
the scan to walk function bodies" plan was based on a diagnosis that
didn't hold up under closer tracing (the scan already walked bodies);
the real bug was two passes disagreeing about how to declare an
already-correctly-identified-as-unresolvable symbol.
