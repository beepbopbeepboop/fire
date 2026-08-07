# HARD BUG (3 related root causes, same underlying pattern): a module's globals-struct/ownership registration scans use the whole-transitive-tree `imported_stmts` superset instead of the module's own statements, corrupting cross-module global attribution at scale

## Status (fixed 2026-08-07, Track B continuation session)

Found while investigating `bugs/CODEGEN_generator_function_Lib_weakref.md`'s
previously-unfixed cluster from first principles (a fresh `python3 mojo.py
build /Users/mrs/net/Python-3.14.6/Lib/weakref.py` run showed 2140 `error:`
lines — a much larger and differently-shaped cluster than the 35-error one
the prior investigation had partially diagnosed, because `weakref.py`
transitively pulls in a much larger module graph — `typing`, `functools`,
`argparse`, `_weakrefset`, `inspect`, `codecs`, `enum`, `pickle`,
`traceback`, `ast`, ... — than the earlier `subprocess.py`-scoped
investigation had exercised). All three fixes are in `gimple_codegen.py`
only.

**2140 -> 700 total `error:` lines** on the same `weakref.py` build (-67%,
1440 errors eliminated) after all three fixes. Full 5-part quality gate
below — 0 regressions, `compile_stdlib.py -j8` unchanged at 664/664.

## Shared root mechanism

`gen_module`'s `imported_stmts` (built in "Phase 0", `do_imports=True`) is
*deliberately* a superset of every statement in the WHOLE transitive
program tree compiled so far, not just the current module's own direct
imports — see `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
rescan.md`'s "Why the reconciliation loop exists" for why that breadth is
genuinely needed (struct/function *visibility* for cross-module symbol
resolution, regardless of which tree level first compiled the defining
module). That doc's Phase 1 fix (2026-08-07, landed just before this
session) made deriving that superset O(1) per level instead of O(N); it
did NOT change (and was explicitly verified not to change) what ends up
IN `imported_stmts`.

The bug this doc covers is a DIFFERENT thing: several places elsewhere in
`gen_module` reuse that same broad, whole-tree `imported_stmts` list for a
purpose that is NOT "resolve visibility of a struct/function defined
anywhere in the tree" but instead "figure out what belongs to THIS
module" (this module's own globals-struct fields; which module a given
global name is really homed in). Because `imported_stmts` contains every
OTHER module's own top-level code too, these consumers attributed
foreign modules' globals to the CURRENT module, at a scale that (for a
small, shallow import graph) mostly went unnoticed but at `weakref.py`'s
much larger transitive closure produced real, cascading GCC errors.

## Mechanism 1 (fixed): `all_scan`/`all_global_scan` (globals-struct field population) included `imported_stmts`, merging every other module's top-level globals into the CURRENT module's own struct

### Root cause

`gen_module`'s "Module-level globals" section (~gimple_codegen.py:31180
and :31229, pre-fix):
```python
all_scan = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
...
all_global_scan = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
```
Both feed `_declared_globals`, which directly populates `self._module_
globals[current_mod_name]` — the field list used to emit `typedef struct
_{module}_toplev { ... }`. Since `imported_stmts` is the whole-tree
superset, ANY top-level `AssignStmt`/`ImportStmt`/`VarDecl` anywhere in
the transitive closure got attributed to `current_mod_name`, regardless
of which module it actually came from.

Confirmed directly via `weakref.py`'s generated `.ci`: `_functools_
toplev` (functools.py's own globals struct) contained fields like
`BINBYTES`/`BOM32_BE` (real module-level globals from `pickle.py`/
`codecs.py`) and `AsyncGenerator`/`Attribute` (names from `ast.py`/
`typing.py`) — none of which `functools.py` itself declares. At
`weakref.py`'s scale (a much larger merged closure than earlier
per-file investigations exercised) this produced real GCC "redefinition
of X" and type-mismatch errors once enough unrelated modules' globals
piled into the same struct.

### Fix

Scoped both scans to just this module's own `stmts`:
```python
all_scan = stmts
...
all_global_scan = stmts
```
Every module already independently registers its OWN globals under its
OWN name via its own recursive `gen_module` call (each transitively-
imported module gets its own `temp_gen` with `module_name=<that
module>`, which runs this exact code with `current_mod_name` set
correctly) — so re-scanning `imported_stmts` here was pure duplicate
registration under the WRONG module name, never load-bearing for
anything. `self._module_globals.get(mod_str)`'s existing cross-module
struct-reconstruction fallback (see `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md`, "mechanism 2") is unaffected —
that logic already only needs the DEFINING module's own field list,
which is unaffected by scoping this scan to `stmts`.

### Verification

`weakref.py` build: 2140 -> 743 errors after this fix alone (`typing.py`'s
error count in particular dropped 1246 -> 25; `_functools_toplev`'s
struct in the regenerated `.ci` no longer contains any foreign field).

## Mechanism 2 (fixed): two independent "unresolved-import auto-stub" code paths use DIFFERENT `#ifndef` guard-macro conventions for the same real symbol, defeating the preprocessor dedup both rely on

### Root cause

Two unrelated auto-stub generators in `gimple_codegen.py` can both decide
to emit a weak "unavailable in compiled mode" stub *definition* for the
exact same never-linked symbol:
1. `gen_module`'s `imported_symbols` preamble loop (~line 32170-32297,
   the "no signature" / `_stub_only_modules` branches) — guarded (or, in
   the `_stub_only_modules` branch, NOT guarded at all) using the bare
   symbol name itself as the `#ifndef` macro (`f"#ifndef {safe}\n..."`).
2. `_lower_named_call`'s `_is_unknown` auto-stub (~line 14515) and
   `_gen_stmt_ExprStmt`'s `_is_unknown_stmt` auto-stub (~line 18170),
   triggered when a call site references the same unresolved name —
   guarded with `_MOJO_STUB_{fname.upper()}` (the convention every OTHER
   stub generator in the file already uses).

Since `get_cache_token` (`functools.py`: `from abc import
get_cache_token`, called at a use site) hits BOTH paths in the same
translation unit, and the two paths guard with DIFFERENT macro strings
(`get_cache_token` vs `_MOJO_STUB_GET_CACHE_TOKEN`), the C preprocessor
never recognizes the second occurrence as "already defined" — both
`__attribute__((weak))` function DEFINITIONS survive into the same
translation unit, a real GCC "redefinition of 'get_cache_token'" error.
The module-global `_emitted_unresolved_stub_syms` dedup set (declared
specifically to prevent exactly this class of bug — see its own
docstring) only covers path (1)'s own two branches against each other;
path (2) doesn't participate in it at all.

### Fix

- Path (1)'s "no signature" branch: guard changed from `f"#ifndef
  {safe}\n..."` to `f"#ifndef _MOJO_STUB_{safe.upper()}\n..."` — matching
  path (2)'s convention exactly, so whichever occurrence is textually
  first in the final `.ci` wins and the other becomes a harmless
  preprocessor no-op (the same pattern every other `_MOJO_STUB_*`-guarded
  stub in this file already relies on).
- Path (1)'s `_stub_only_modules` branch (`jit.arm64`/`jit` — rare, only
  hit by this repo's own self-hosting build): was emitted completely
  UNGUARDED (no `#ifndef` at all). Added the same `_MOJO_STUB_{name.
  upper()}` guard for defense-in-depth/consistency, even though no
  concrete double-definition was observed for this narrower branch in
  this session's testing.

### Verification

`weakref.py` build: 743 -> 710 after this fix (`functools.py`'s
"redefinition of 'get_cache_token'" error class gone; the reported line
number for the (unrelated, still-latent) misattribution issue also
shifted, consistent with less duplicated preamble text — see `bugs/
CODEGEN_generator_function_Lib_weakref.md` for the line-attribution
finding this is NOT fixing).

## Mechanism 3 (fixed): the shared, by-reference `self._global_to_module` dict gets silently reassigned to a fresh, module-private `{}` mid-`gen_module`, breaking cross-instance sharing for every consumer downstream of that point

### Root cause

Two bugs compounded:

1. **Ownership mis-attribution in the "Phase 1.7" pre-scan.** `gen_module`'s
   Phase 1.7 (~line 30103, "pre-scan global variable declarations", which
   independently duplicates roughly what Mechanism 1 covered for a
   different purpose — populating `_global_var_types` early enough for
   `_lower_IdentExpr` to see it) also scans `stmts + imported_stmts` and
   does `if _gname not in self._global_to_module: self._global_to_module
   [_gname] = _phase17_mod` where `_phase17_mod = self.module_name or
   "root"` — i.e. "whichever module's OWN Phase-1.7 scan happens to reach
   this name FIRST claims ownership", even when the name was only
   reachable via the foreign `imported_stmts` superset, not that module's
   own `stmts`. Fixed by restricting the ownership WRITE (not the
   `_global_var_types` type-visibility population, which stays sourced
   from the full `stmts + imported_stmts` — this preserves cross-module
   type inference for e.g. an inherited method spliced from a different
   origin module, see `_merge_struct_inheritance`) to statements that are
   actually `id()`-identical to this module's own `_flatten_resolved_
   conditionals(stmts)` output.

2. **A later, unconditional reassignment throws the shared dict away.**
   `gen_module`'s "Module-level globals" section (~line 31565, pre-fix)
   did:
   ```python
   self._global_to_module: dict[str, str] = {}
   for gname in sorted(_declared_globals):
       ...
       self._global_to_module[gname] = current_mod_name
   ```
   `_global_to_module` is declared in `__init__` as an explicitly SHARED
   (by-reference) dict — `temp_gen._global_to_module = self._global_to_
   module` in `_compile_imported_module` shares the SAME object into
   every nested `temp_gen` in the whole tree, exactly like `_module_
   stmts`/`_all_transitive_stmts_ordered`/etc. Reassigning the attribute
   here silently DETACHES this one instance from that shared object going
   forward: every entry any OTHER module wrote into the original dict
   stays correct there, but THIS instance's own later reads (in
   particular `_lower_IdentExpr`'s bare-identifier "does this name belong
   to some OTHER module" check, run during this SAME `gen_module` call's
   later statement-lowering phase, well after this reassignment) only
   ever see a narrow, freshly-rebuilt view containing just `current_mod_
   name`'s own globals — losing all ownership information about every
   OTHER module's globals that Phase 1.7 (bug 1, above) or an earlier
   nested `temp_gen` had already correctly recorded.

Combined, these two bugs meant a BARE identifier lowered by `_lower_
IdentExpr` (~line 8044's `name in self._global_var_types` guard) had no
reliable way to tell "this name is genuinely MY OWN module's global" from
"this name merely happens to match some OTHER module's same-named
global, visible only because of the whole-tree `_global_var_types`
superset" — `_lower_IdentExpr` blindly trusted ANY match in `_global_var_
types` as belonging to `self.module_name`'s own struct.

Real-world trigger, found via `mojo.py`'s own self-host build (`make
check-selfhost`, exercised as this session's mandatory quality gate — NOT
via `weakref.py`): `gimple_codegen.py`'s own `compile_to_gimple_cached`
has a `filename` parameter, closed over by an internal `lambda:
compile_to_gimple(mojo_src, do_imports, filename)`. This codegen's
closure-capture support for lambdas capturing an ENCLOSING function's own
parameters is a known, pre-existing, separate limitation (the sibling
captures `mojo_src`/`do_imports` in the exact same lambda correctly fall
back to the generic `/* ct param or undeclared: X */` 0-placeholder,
confirming this is an accepted, already-documented gap, not something
this fix touches) — but `filename` specifically did NOT fall back to that
placeholder: `mojo_compiler.py` has its own, completely unrelated
top-level `filename = sys.argv[1] if len(sys.argv) >= 2 else "<stdin>"`
(inside `if __name__ == "__main__":`), and `_lower_IdentExpr` resolved
gimple_codegen.py's own captured `filename` parameter as if it were a
read of `_gimple_codegen_globals.filename` — a field `gimple_codegen.py`
never declares — producing `error: 'struct _gimple_codegen_toplev' has
no member named 'filename'` and breaking `make check-selfhost` outright.
(This was NOT present in the `weakref.py` error count above — surfaced
purely by fixing Mechanism 1, which removed the ACCIDENTAL, unintentional
"masking" effect the OLD over-broad pollution provided: before Mechanism
1's fix, `filename` really WAS a spurious field on `_gimple_codegen_
toplev` too, so the access compiled — with the wrong value, silently.)

### Fix

- Phase 1.7: track `id()`s of this module's own flattened `stmts` in a
  set, and only write `self._global_to_module[_gname] = _phase17_mod`
  when the source statement is actually one of them (not merely present
  somewhere in `imported_stmts`).
- "Module-level globals" section: removed the `self._global_to_module:
  dict[str, str] = {}` reassignment entirely — the loop right below it
  now just ADDS this module's own entries into the SAME shared dict
  object every other consumer in the tree is still holding a reference
  to, exactly like Phase 1.7's own (now-fixed) writes already do.
- `_lower_IdentExpr`'s global-vs-local guard (~line 8044): as a
  defense-in-depth safety net independent of the two data-side fixes
  above, added an explicit check that a bare identifier is only treated
  as THIS module's global when `_global_to_module.get(name)` is either
  unset or equals `self.module_name` — a bare name can never legitimately
  resolve to a different module's global under real Python scoping (that
  needs explicit `othermodule.name` qualification, a completely separate,
  unaffected `MemberExpr`-lowering code path).

### Verification

- Standalone repro (`gimple_codegen.compile_to_gimple_cached(open(
  'mojo.py').read(), do_imports=True, filename=...)`, grep the resulting
  `.ci` for `_gimple_codegen_globals.filename`): present before this fix,
  gone after.
- `make check-selfhost` / `python3 test_selfhost.py`: was FAILING (`0
  passed, 1 failed`, `'struct _gimple_codegen_toplev' has no member named
  'filename'` plus a same-shape `build_stdlib_dylib.py`/`'src'` error) at
  the point Mechanism 1's fix alone had landed; **passing again** (`1
  passed, 0 failed`) after Mechanisms 1+3 together.
- `weakref.py` build: 710 -> 700 (small additional reduction; this fix's
  primary value is the self-host regression it closes, not weakref.py's
  own count).

## Also fixed in the same session, filed separately

`bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_
ordinary_code.md`'s "option 3" (defensive net against an empty resolved
`self` type in the getattr-dispatch-table machinery) was implemented in
this same session — see that doc's own updated Status section. Not
folded into this doc since it's a different subsystem (`DispatchTable`/
`_plan_dispatch_tables`, not `gen_module`'s globals-struct machinery) and
was already tracked under its own hard-bug doc.

## Quality gate (2026-08-07, all three mechanisms + the getattr-dispatch fix together)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` (`python3 test_selfhost.py`) — clean (`1 passed,
   0 failed`, "self-host compiles + links clean"). This gate FAILED at
   the point only Mechanism 1 had landed (see Mechanism 3's "real-world
   trigger" above) — Mechanism 3 was found and fixed specifically to
   restore this gate, not discovered independently.
4. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib` +
   `build_stdlib_dylib.build_stdlib(jobs=8)`) — clean, 0 `skip <module>:`
   lines.
5. `python3 compile_stdlib.py -j8` — **664/664 passed, 0 unexpected
   failures** (unchanged from baseline — no regression from any of the
   fixes in this doc).

## Not fixed / still open

`weakref.py`'s build still does not succeed (700 errors remain, down from
2140). The largest remaining single-file cluster (405 errors,
`_weakrefset.py`) is a DIFFERENT bug — a real `#line` filename-
misattribution (inherited-mixin-method flattening splices foreign-origin
AST nodes into a struct's `.methods` without any per-node origin-file
tracking, so `gen_stmt`'s `#line` emission always uses `self._current_
filename`, i.e. whichever module is CURRENTLY being compiled, not the
node's true origin file) COMPOUNDED with a real module-symbol-
qualification gap (`enum`'s dispatch-solver — a separate class from the
`GimpleGen` machinery this doc covers — records unqualified callee names
like `Enum___copy__`, but the real compiled symbol is module-qualified
`enum_Enum___copy__` once `bugs/hard/CODEGEN_same_bare_name_struct_
collision_across_modules.md`'s cross-module qualification machinery
renames it — task #141, explicitly out of scope for this session).
Neither was attempted here — see `bugs/CODEGEN_generator_function_Lib_
weakref.md`'s own updated "Not fixed" section for the full writeup and
why the second one specifically was left alone.
