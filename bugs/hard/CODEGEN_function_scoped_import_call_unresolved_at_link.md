# HARD BUG: a function-scoped (local) `from X import Y` followed by calling `Y(...)` compiles clean but leaves an undefined symbol at LINK time

## Status (updated 2026-08-07, final): Mechanism 1 FIXED and kept; Mechanism 2 fix reverted after a corpus-wide regression

Two independent investigations this session each found and fixed a real,
different mechanism contributing to this symptom, developed in parallel
on isolated worktrees without knowledge of each other. Their combined
effect, and the eventual outcome, was re-verified directly against
actual rebuilds (not assumed from either fix's own isolated claim) —
**Mechanism 1's fix is kept, Mechanism 2's fix was reverted**:

- `Lib/importlib/resources/_common.py`: **builds and links clean**
  (confirmed via direct rebuild in the final state) — Mechanism 1's fix
  alone is sufficient for both of this file's original findings
  (`_wrap_spec`, `_next`).
- `Lib/runpy.py`: **builds and links clean** (confirmed via direct
  rebuild in the final state) — same, Mechanism 1's fix alone resolves
  the original `read_code`/`get_importer` link failure.
- `Lib/importlib/__init__.py`: **builds clean** (confirmed via direct
  rebuild) — this file was NEVER broken by Mechanism 1's fix; it was
  only regressed while Mechanism 2's fix was also present (see below),
  and is back to passing now that Mechanism 2 is reverted.

This is a genuine, instructive case of two fixes interacting: Mechanism
2's fix (making `_parsed_import` able to genuinely resolve+inline a
sibling/relative-import file it previously couldn't find at all) is
exactly what newly exposed two SEPARATE, pre-existing, previously-
unreachable bugs — a `_abc`/`abc` globals-struct redefinition collision
in `_common.py`'s transitive closure, and an unrelated GIMPLE-type bug
in `_bootstrap.py` that broke `importlib/__init__.py`. Mechanism 1's
fix (routing an unresolvable import through a weak STUB instead of a
bare, definition-less extern) never actually inlines the sibling file
for real, so it never exposes either of those latent bugs — it "papers
over" the missing resolution with a safe no-op stub, which is why it's
lower-risk and was kept.

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

## Root cause: TWO independent mechanisms

The original hypothesis ("the cross-module import scan only walks
top-level statements, not function bodies") was WRONG for both. Link
mode's actual pre-pass, `_register_link_imports` (`gimple_codegen.py`),
already has a `scan()` helper that explicitly recurses into
`FunctionDef`/`IfStmt`/`WhileStmt`/`ForStmt`/`TryStmt` bodies looking
for `FromImportStmt` nodes — it finds `from pkgutil import read_code`/
`from ._adapters import wrap_spec` just fine, at exactly the depth
these two examples live at.

### Mechanism 1 (FIXED, kept): `_register_link_imports.scan()`'s two
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

**Fix (kept)**: two coordinated changes in `gimple_codegen.py`:
1. `_gen_stmt_FromImportStmt` (~line 19083): only write the bare
   fallback entry when there ISN'T already a fuller entry (one with a
   `'signature'` key) from an earlier pass — don't downgrade a real
   resolution.
2. The preamble's "no signature" branch (~line 32503): changed
   `if self.do_imports:` to `if self.do_imports or self.link_imports:`
   so link mode routes through the same weak-stub-definition path
   `do_imports=True` already used, instead of falling into the
   bare-extern-with-no-definition `else` branch (now scoped explicitly
   to `do_imports=False AND link_imports=False`, i.e.
   compile_stdlib.py's genuinely-separate-.o workflow, where the
   assumption that "another translation unit defines it" is actually
   true).

This fix is deliberately LOW-blast-radius: it changes how an
ALREADY-classified-as-unresolvable import declares itself (a working
stub vs. a bare dangling extern) — it can only turn a previously-broken
link into a working one, never change behavior for anything that
resolves normally, and it never causes a previously-unreachable file to
become newly reachable (the stub is a no-op, not a real inlined body).

### Mechanism 2 (fix implemented, verified clean, then REVERTED):
`_parsed_import` can't locate a plain sibling `.py` file or a
leading-dot relative import at all

The gap Mechanism 1's fix papers over (with a stub) is one step
earlier: `_register_link_imports.scan()` calls a local `_exports
(module)` helper to resolve the imported module's signature — first
via `imports.resolve(module)` (a real dylib), then falling back to
`self._parsed_import(module)` + `load_module(module)` (source-level
text extraction) for a module with no dylib. `_parsed_import` only ever
tried `imports.resolve_source(module)` and `self._resolve_test_relative_
module(module)` — BOTH scoped to this project's own std/test module
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

**Fix implemented and verified clean, then reverted**: two additive
changes in `gimple_codegen.py` — a new `_module_search_candidates`
helper (extracted from `_compile_imported_module`'s path-building
logic, plus a new leading-dot relative-import branch), and
`_parsed_import` falling back to it when both existing resolvers return
nothing. This DID correctly make `_parsed_import` resolve `pkgutil.py`
and `_adapters.py` for real (confirmed via direct C-output inspection),
and passed the full mandated 5-step quality gate completely clean
(test_gimple.py 247/247, test_module_cache.py 76/76, check-selfhost
clean, dylib rebuild 0 skips, compile_stdlib.py -j8 664/664 0
unexpected — byte-identical to baseline).

**But it was reverted**, for two compounding reasons found only after
the gate passed clean:
1. Neither of the two ORIGINAL confirmed instances (`runpy.py`,
   `importlib/resources/_common.py`) actually reached a passing
   `mojo.py build` even WITH this fix — both hit separate, unrelated,
   deeper bugs newly reachable once their transitive closure resolved
   correctly: `_common.py` hit a `_abc`/`abc` globals-struct
   redefinition collision (`Lib/importlib/_abc.py` and
   `Lib/importlib/abc.py` both getting inlined into the same
   translation unit — the SAME class of bug as the already out-of-scope
   `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`,
   task #141); `runpy.py` hit a different, larger error set including
   `importlib/abc.py`-internal redefinition/conflicting-type errors and
   an `implicit declaration of function '_write_atomic'`. Zero observed
   P/F flips on the fix's own motivating instances.
2. Independently spot-checking OTHER already-passing `COMPILE_FAIL_*.md`
   files (routine corpus re-triage, not triggered by any specific
   suspicion) found the fix **regresses `Lib/importlib/__init__.py`
   from a clean PASS to a hard COMPILE_FAIL** — a file with no known
   connection to this bug, not touched by any of the fix's own testing.
   Root cause: `importlib/__init__.py` does `from . import _bootstrap`,
   and the SAME fix that correctly resolves `pkgutil`/`._adapters`
   ALSO now resolves `_bootstrap.py` (previously silently unresolved
   and never inlined at all) — but `_bootstrap.py` has its own
   pre-existing, unrelated GIMPLE-type bug (`non-trivial conversion in
   'integer_cst'`, a `char* -> int64_t` pointer/integer mismatch) that
   was never reachable before because `_bootstrap.py` was never
   actually compiled as part of this file's closure. Confirmed via a
   direct before/after comparison of the same patch: WITHOUT the fix,
   `mojo.py build Lib/importlib/__init__.py` → rc=0; WITH the fix, same
   command → rc=1.

**None of the 5 mandated gates caught this** — `compile_stdlib.py`
tests this project's own `std.*` Mojo modules (which resolve via real
dylibs, never hitting this specific source-level fallback path),
`check-selfhost` tests this compiler's own Python source (single-file,
no sibling/relative multi-file imports of this shape), and
`test_gimple.py`/`test_module_cache.py` are unit-level. The actual
regression only showed up against the Python-3.14.6 `COMPILE_FAIL_*.md`
corpus this task exists to improve — a concrete instance of this
project's standing principle that a change passing the mandated gate is
not sufficient evidence of no regression; the actual corpus this work
targets needs its own re-triage before considering a cross-cutting
import-resolution change landable.

**Conclusion**: Mechanism 2's fix is not viable as committed — its
value (correctly resolving two more import shapes) is real, but its
side effect (newly resolving OTHER previously-silently-unresolved
sibling/relative imports across the ENTIRE Python-3.14.6 corpus, each
of which may have its own independent, latent, never-before-reachable
bug) gives it a blast radius far larger than "the two motivating
files," and it's effectively untestable in full without re-running the
ENTIRE corpus for every candidate change. **Reverted, code fully
removed from `gimple_codegen.py`.** A future attempt should either (a)
make the newly-resolved inline-fallback path fail SOFT — falling back
to the old "unresolved, stub it out" behavior — when the sibling module
itself doesn't compile clean, rather than propagating its error up
through the whole client build, or (b) re-run the full `COMPILE_FAIL_*`
corpus triage (not just the specific instances motivating the fix)
before considering it landable.

## Quality gate (2026-08-07, final state — Mechanism 1 only)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).

Direct rebuilds confirming the final state (all three files, via
`python3 mojo.py build <file>`, checked for `error:`/`link failed`
lines): `Lib/runpy.py` clean, `Lib/importlib/resources/_common.py`
clean, `Lib/importlib/__init__.py` clean.

## Risk assessment

Mechanism 1's fix: LOW risk, confirmed by both its own isolated gate
run and this doc's final combined-state re-verification. It only
changes how an already-classified-as-unresolvable import declares
itself — cannot make a previously-working case stop working.

Mechanism 2's fix: turned out to be HIGH risk despite passing every
mandated gate clean — a genuine illustration of why this project treats
"passed compile_stdlib.py cleanly" as necessary but not sufficient
evidence of safety for changes touching cross-module import resolution,
alongside this project's other two documented "passed the gate but
still regressed something" incidents.
