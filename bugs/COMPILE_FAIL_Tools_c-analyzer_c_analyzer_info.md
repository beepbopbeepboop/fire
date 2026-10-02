# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-09-30 — this file's own gcc errors are ONE root cause, and it belongs to another worker's claim

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). Ten
gcc errors, all one family, all from the SAME module-level global name:

```
info.py:79:8:  error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast
info.py:81:8:  error: (same)
info.py:93:8:  error: (same)
info.py:185:7: error: (same)
info.py:111:1: error: non-trivial conversion in 'component_ref'   x4
info.py:223:1: error: non-trivial conversion in 'component_ref'   x2
```

with gcc naming the offending expression:

```
int64_t
char *
_t6 = _c_common_tables_globals.UNKNOWN;
```

### The mechanism

`c_analyzer/info.py` defines its OWN `UNKNOWN`:

```python
IGNORED = _misc.Labeled('IGNORED')     # a struct-typed module global
UNKNOWN = _misc.Labeled('UNKNOWN')
```

`c_common/tables.py` also defines `UNKNOWN = '???'` — a `char *`. A bare
reference to `UNKNOWN` inside `c_analyzer/info.py` (`typedecl in (UNKNOWN,
IGNORED)`, `return UNKNOWN, extra`, `typedecl = UNKNOWN`, …) is emitted
against **`c_common.tables`'** globals struct. So:

* the wrong module's slot is read, and
* the local is typed `int64_t` while the slot it reads is `char *`.

Two modules sharing one bare name, each reference resolving through whichever
slot won — that is
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`, which
is **claimed by another worker** (`hard-same-name-struct`). Per the parallel-work
rules I did not edit it. It also correctly predicts the symptom: the loser's
access resolves against the winner's slot.

### Next step (for whoever holds that claim, or after it lands)

1. The bare-name resolution must be module-scoped for module GLOBALS the way
   it already is for functions (`_func_qualifier`) and structs
   (`_imported_struct_home`). `c_analyzer/info.py` references its own
   `UNKNOWN` — it is in `self._module_globals` / `_local_top_level_func_names`
   territory already, so the fix is that the global slot lookup consult the
   same tier order instead of one shared bare-name slot.
2. Verify against BOTH names at once: `IGNORED` exists only in
   `c_analyzer/info.py`, `UNKNOWN` in both `c_analyzer/info.py` and
   `c_common/tables.py`, and `c_parser/info.py` has its own pair again — three
   modules, two names, so a fix that resolves the winner differently per
   module is testable.
3. A CPython-comparison regression must print, compiled, the value of
   `c_analyzer.info.UNKNOWN` next to `c_common.tables.UNKNOWN` and show them
   DIFFERENT (`Labeled('UNKNOWN')` vs `'???'`). A test that only prints one of
   them cannot catch this.

### Meanwhile, this file cannot build even with that fixed

Three imported modules fail in this closure, unchanged:

```
# ERROR: compiling imported module 'c_parser.info'      -> cannot materialize a generator as a list: no known generator API for 'rendered'
# ERROR: compiling imported module 'c_parser/parser/_func_body.py' -> cannot coerce MojoDict * to MojoList * ... value='_t513' dest='data'
# ERROR: compiling imported module 'c_parser.match'      -> cannot coerce MojoSet * to MojoList * ... value='_t6' dest='expected'
```

(`c_parser/preprocessor` was the fourth and is fixed — commit `b67c170e`.)
All three are documented in
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`'s "Next
step", which is the more actionable list: this file's own ten errors are one
foreign-claim bug, but its imported-module floor is three unclaimed ones.
