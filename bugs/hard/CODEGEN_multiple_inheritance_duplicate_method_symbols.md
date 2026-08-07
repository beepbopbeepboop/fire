# HARD BUG (FIXED 2026-08-06): whole-file self-referential import duplicates every symbol, misdiagnosed as a multiple-inheritance struct-merge bug

## Status

**FIXED.** The original hypothesis below (an `all_struct_defs`/
`_merge_struct_inheritance` struct-list duplication specific to
multiple-inheritance classes) was investigated first, per the doc's own
"what a real fix needs" plan, and turned out to be **wrong**. The real
root cause, confirmed against the actual generated `.ci`, is a totally
different (and much more general) bug: `Lib/importlib/abc.py`'s own
`import abc` statement — a normal, absolute, top-level import of the
*real* `Lib/abc.py` (`abc.ABCMeta`) — gets resolved by
`_compile_imported_module`'s search-path order back to
**`Lib/importlib/abc.py` itself**, because the importing file's own
directory (`Lib/importlib/`) is searched before any path that could
reach the genuine top-level `Lib/abc.py`, and a file named `abc.py`
exists right there — the file currently being compiled. The whole
module gets parsed and `gen_module`'d a **second time** as if it were a
distinct imported dependency, and its entire top-level content
(literally every class, not just the multiple-inheritance ones) is
emitted twice into the one flattened translation unit.

Fixed by gimple_codegen.py commit (see this doc's own repo history for
the exact commit): a new path-identity self-import guard,
`GimpleGen._compiling_file_paths` (a `set[str]` of absolute paths
currently being compiled anywhere in the whole-program closure, shared
by object reference across every nested `temp_gen` the same way
`_compiled_modules` already is). Every root entry point
(`compile_to_gimple`, `compile_to_gimple_with_cpp`, `compile_linked`)
seeds it with `os.path.abspath(filename)` right where it already sets
`gen._current_filename`. `_compile_imported_module`'s `for path in
mojo_paths:` resolution loop now skips (via `continue`, trying the next
search-path candidate) any candidate whose absolute path is already in
that set, instead of unconditionally accepting the first existing
match. `python3 mojo.py build Lib/importlib/abc.py` went from ~26
`redefinition of 'abc_*'` errors (spanning `MetaPathFinder`,
`PathEntryFinder`, `ResourceLoader`, `InspectLoader`, `ExecutionLoader`,
`FileLoader`, `SourceLoader` — literally every class in the file, not
just the two multiple-inheritance ones originally suspected) down to
just the two pre-existing, separately-tracked `__func__` errors (see
"Separate, already-tracked issue" below).

## Why the original hypothesis looked plausible but was wrong

The symptom (`redefinition of 'abc_FileLoader_get_data'` etc.) and the
two classes named in the original write-up (`FileLoader`/`SourceLoader`)
are real — but they're not special. A full, ungrepped build log showed
the SAME error for `MetaPathFinder.invalidate_caches`,
`PathEntryFinder.invalidate_caches`, `ResourceLoader.get_data`,
`InspectLoader.is_package/get_code/get_source/source_to_code`,
`ExecutionLoader.is_package/get_source/source_to_code/get_filename/
get_code` — none of which use multiple inheritance at all
(`MetaPathFinder`/`PathEntryFinder` have no bases beyond
`metaclass=abc.ABCMeta`; `ResourceLoader`/`InspectLoader` inherit from
a single `Loader`). The original investigation's "roughly 20 errors,
all tracing to TWO classes" underestimate came from a partial grep, not
a full read of the error log — a full run showed every top-level class
in the file affected equally, which is the actual signature of "the
whole file got compiled twice," not "multiple-inheritance method lists
got inflated and then duplicated." Confirming this directly against the
generated `.ci` (dumped via `gimple_codegen.compile_to_gimple` on the
real file) showed a literal byte-identical duplicate of the entire
`#line 1 ".../abc.py"` section — including function bodies with
matching real source line numbers — appearing twice in the same
translation unit, which rules out a struct-list/method-merge bug (that
class of bug would inflate ONE struct's `.methods`, not duplicate the
whole file's every class+function).

## Root cause, precisely

`_compile_imported_module` (gimple_codegen.py, `_compile_imported_module`)
builds its search order as:
```
search_dirs = extra_search_paths + [importer_dir] + ['.', '..', script_dir]
mojo_paths  = [os.path.join(d, f"{module_name}{ext}")
               for d in search_dirs for ext in ('.py', '.mojo')]
```
`importer_dir` is the directory of the file **currently being
compiled** — i.e. for `Lib/importlib/abc.py`, `importer_dir =
Lib/importlib/`. This directory is checked FIRST (a deliberate design
choice supporting sibling `.mojo`/`.py` imports — see BUG-2026-014's
comment on this same function), ahead of anything that could resolve a
genuinely absolute top-level import correctly. For `import abc` inside
`Lib/importlib/abc.py`, `module_name == "abc"`, and the very first
candidate tried is `Lib/importlib/abc.py` — the file being compiled —
which of course exists. `_compile_imported_module`'s `for path in
mojo_paths: if os.path.exists(path): ... return (code, stmts)` accepts
the FIRST existing candidate unconditionally, so it never even reaches
a location that might hold the real top-level `Lib/abc.py` (which, as
it happens, this compiler's search-path list — rooted at the CWD the
compiler was invoked from and the importing file's own directory, with
no notion of "the CPython Lib/ package root" — couldn't have found
anyway; `import abc` from `Lib/importlib/abc.py` now correctly resolves
to nothing, i.e. an ordinary "not found, fall through to extern/stub"
unresolved import, same as any other genuinely-external stdlib
reference this compiler can't chase).

This is a **general** bug, not specific to `importlib/abc.py`: ANY file
whose basename matches the bare name of a DIFFERENT, unrelated
top-level module it imports (a real, if not overwhelmingly common,
Python package-authoring pattern — a package submodule shadowing a
top-level module of the same name, exactly `importlib/abc.py` importing
`abc`) would trigger the identical whole-file self-duplication.

## The fix

Add a path-identity self-import guard, `GimpleGen._compiling_file_paths:
set[str]`, tracking absolute file paths currently being compiled
anywhere in the whole-program closure (mirrors `_compiled_modules`'s
existing sharing pattern: assigned by direct object reference onto
every nested `temp_gen` `_compile_imported_module` constructs, so a
DEEPER indirect cycle — A imports B, B imports A — is caught too, not
just a literal direct self-import).

- Every root entry point that starts a whole-program compile
  (`compile_to_gimple`, `compile_to_gimple_with_cpp`, `compile_linked`)
  seeds this set with the root file's own absolute path, right next to
  where each already does `gen._current_filename = filename`.
- `_compile_imported_module`'s `for path in mojo_paths:` loop now
  computes `os.path.abspath(path)` for each candidate and `continue`s
  (tries the NEXT search-path candidate) if that path is already in
  `_compiling_file_paths`, instead of accepting it as the resolved
  module. This is deliberately NOT a "give up on this import entirely"
  bail-out: it lets resolution correctly fall through to a genuinely
  different, later search-path candidate of the same bare name (the
  general case this compiler already needs to handle for legitimate
  same-basename-in-different-directories imports).
- The chosen path is added to `_compiling_file_paths` as soon as it's
  accepted (before recursing into its own compile), mirroring
  `_compiled_modules.add(module_name)`'s existing immediate-registration
  pattern, so a deeper cycle is caught before infinite recursion.

Considered and rejected: reordering `search_dirs` so `importer_dir`
isn't checked before a "real" absolute-import resolution. Rejected
because (a) there is no real notion of a package/sys.path root in this
compiler for arbitrary CPython `Lib/` source — `importer_dir`-first is
relied on throughout for legitimate sibling `.mojo`/`.py` imports
(BUG-2026-014), and reordering it is exactly the kind of broad,
narrowly-motivated change to shared import-resolution machinery
CLAUDE.md's quality gate exists to catch; (b) the path-identity guard
fixes the actual observed failure mode (self-duplication) without
touching resolution order or priority for any other import shape at
all — genuinely different files that happen to share a bare module
name are completely unaffected.

## `_struct_name_owner` is unrelated

This bug's original write-up asked whether `_struct_name_owner` (the
existing same-bare-name struct-across-modules collision guard, see
bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md)
was "supposed to" cover this case. It is not, and could not: that
mechanism dedupes FIELD/TYPE registration for two unrelated classes
that happen to share a bare name (e.g. this repo's own `FunctionDef`
appearing in both `mojo_compiler.py` and the dead `ast_nodes.py`) — it
never touches the METHOD-BODY C-emission loop at all (`gen_module`'s
`for stmt in stmts: elif isinstance(stmt, StructDef): ... for m, oid in
zip(stmt.methods, moids): func_parts.append(self._gen_struct_method(...))`),
which walks only the CURRENT module's own top-level `stmts` — one pass,
no duplication possible from THAT loop alone. The actual duplication
happened one level up: `stmts` itself was the SAME file's AST parsed
and handed to `gen_module` twice (once as the root module, once again
as a supposedly-separate "imported" dependency of itself).

## Separate, already-tracked issue in the same file

```
error: expected identifier before '__func__'
```
at:
```python
if self.path_stats.__func__ is SourceLoader.path_stats:
    raise OSError
```
`self.path_stats.__func__` (accessing a bound method's underlying
function object) is a dynamic-attribute-on-generic-object case, already
covered by bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
Sub-case C (`MojoBoundMethod` dunder-attribute access) — out of scope
for this fix, confirmed still present (2 occurrences) after this fix
landed; `python3 mojo.py build Lib/importlib/abc.py 2>&1 | grep error:`
now shows exactly these 2 and nothing else.

## Verification

- Minimal repro (`pkg/mymod.py`: `import mymod` at top, plus an
  ordinary class with one method) — before the fix, the method's C
  symbol appeared twice (forward-decl + body, in each of two identical
  `#line 1 "mymod.py"` sections); after the fix, exactly once, and the
  built executable runs and prints the expected value.
- Real file: `python3 mojo.py build
  /Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py` — error count went
  from ~26 (all `redefinition of 'abc_*'` plus the 2 `__func__` errors)
  to exactly the 2 `__func__` errors.
- Full 5-part quality gate: `test_gimple.py` (247/247), `test_module_
  cache.py` (76/76), `make check-selfhost` (pass), from-scratch stdlib
  dylib rebuild (0 `skip <module>:` lines), `compile_stdlib.py -j8`
  (see bugs/COMPILE_FAIL_importlib_abc.md and the commit message for
  the exact before/after pass counts).
