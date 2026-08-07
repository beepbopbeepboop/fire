# COMPILE_FAIL: Lib/importlib/_bootstrap_external.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py`

## Status (updated 2026-08-06)

Two of four originally-found issues FIXED (commit fd29316, plus the
earlier platform-branch-selection fix 7014dde from a prior session).
Two remain, not yet root-caused.

### FIXED: platform-conditional-def branch selection (7014dde, prior session)

`if _MS_WINDOWS: def _path_join(...): ...(Windows logic)... else: def
_path_join(...): ...(POSIX logic)...` used to always compile the WINDOWS
branch regardless of actual platform — a silently-wrong-runtime-behavior
bug, not just a compile failure. `gen_module`'s conditional-toplevel-def
promotion now resolves `sys.platform`-derived conditions and picks the
actually-correct branch.

### FIXED: global-list element type + conditional-global visibility (fd29316, this session)

```
error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast
```
at `_path_join`'s own `return path_sep.join([...])` (POSIX branch, now
correctly selected per the fix above) and a second occurrence at line
329. Root-caused to TWO compounding gaps in `gen_module`'s "Phase 1.7"
global-variable pre-scan:

1. It recorded a global list/tuple literal's own C type (`MojoList *`)
   but never its ELEMENT type, so `_quick_type`'s `SubscriptExpr` case
   (reading element types from `self._elem_types`) always fell through
   to `int64_t` for `OTHER = SOME_GLOBAL_LIST[idx]` — the real shape here
   is `path_sep = path_separators[0]`, `path_separators` being a global
   list of one-character strings.
2. The pre-scan only recognized a plain top-level `AssignStmt`, never
   descending into an `IfStmt`'s branches — so `path_separators` itself,
   assigned via `if _MS_WINDOWS: path_separators = [...] else:
   path_separators = [...]`, was invisible to the pre-scan (and thus fix
   #1 above) entirely.

Fixed both: element-type recording for global list/tuple literals, and
an iterative (non-self-recursive, matching this file's own established
self-host-safety convention for the def-promotion pass) flattening pass
that resolves any top-level conditional whose condition folds to a known
platform-constant bool down to just its correct branch before the
pre-scan runs. Full quality gate verified clean (test_gimple.py 247/247,
test_module_cache.py 76/76, check-selfhost clean, dylib rebuild 0 skips,
compile_stdlib.py -j8 664/664 0 unexpected).

### NOT YET FIXED: `_write_atomic.__code__` at module scope

```
error: implicit declaration of function '_write_atomic'; did you mean '_write_atomic_132aaf'? [-Wimplicit-function-declaration]
```
at:
```python
_code_type = type(_write_atomic.__code__)
```
`_write_atomic` is an ordinary top-level function referenced as a VALUE
(not called) at MODULE scope, to read its `.__code__` attribute. The
generated C calls the BARE, unmangled name `_write_atomic()` where it
should reference the real mangled C symbol (`_write_atomic_132aaf`, per
GCC's own suggestion). Not root-caused further — likely a gap in
function-as-value resolution specific to MODULE-level statements (as
opposed to inside another function's body, where a similar case —
`_closure_value_locals` — is already handled for LOCAL variables holding
a closure/function value; this is the analogous MODULE-level gap, for a
plain top-level function rather than a closure).

Confirmed a second, independent real-world instance 2026-08-06 via
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md`:
`Tools/c-analyzer/c_analyzer/__main__.py` defines `fmt_raw`/`fmt_brief`/
`fmt_summary`/`fmt_full` as ordinary top-level functions, then builds a
module-level dispatch dict from them as VALUES (`FORMATS = {'raw':
fmt_raw, 'brief': fmt_brief, ...}`) — same "function name used as a
bare VALUE at module scope" shape, same symptom (`'fmt_brief_0c85c9'
undeclared here (not in a function); did you mean
'_funcptr_fmt_brief_0c85c9'?` — GCC's own suggested fix names the exact
already-generated-but-unused `_funcptr_*` static pointer this call site
should have referenced instead of the bare name).

### NOT YET FIXED: "invalid conversion in gimple call" at lines 960, 1190

```
error: invalid conversion in gimple call
```
Both sites are inside methods with `if/else`-branched `with` blocks
whose two branches return from structurally different context-manager
types (line 960's `get_data`: `with _io.open_code(...) as file: return
file.read()` vs `with _io.FileIO(path, 'r') as file: return
file.read()`). Not root-caused — not yet determined whether this is a
`with`-statement return-type-unification gap, an `_io.open_code`/
`_io.FileIO` signature-modeling gap, or something else. Worth a focused
follow-up session given it recurs at two separate call sites in this
file.
