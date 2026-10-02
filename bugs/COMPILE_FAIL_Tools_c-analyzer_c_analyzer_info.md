# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/info.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/info.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-01 — this file's OWN ten errors are GONE (10 → 0). Three UNRELATED imported-module blockers remain, and the doc's "foreign-claim" caveat turned out to be wrong about one thing

`python3 fire.py build .tmp/ca/c_analyzer/info.py` (sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`) on the pre-fix tree
(`1d5a25ed`) versus this branch:

```
before:  10 error: lines, ALL ten of the single UNKNOWN family
after:    3 error: lines, NONE of them the UNKNOWN family
```

Before, verbatim and complete:

```
info.py:184:7: error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast
info.py:80:8:  error: (same)
info.py:79:8:  error: (same)
info.py:93:8:  error: (same)
info.py:111:1: error: non-trivial conversion in 'component_ref'   x4
info.py:223:1: error: non-trivial conversion in 'component_ref'   x2
```

After, verbatim and complete:

```
info_gen.cpp:140:27: error: request for member 'render' in 'self->Analyzed::item',
                              which is of non-class type 'int64_t'
info_gen.cpp:156:30: error: invalid types 'int64_t[int]' for array subscript
info_gen.cpp:157:24: error: invalid types 'int64_t[int]' for array subscript
```

### What was actually wrong — THREE defects, one per layer, not one

The doc's mechanism section was right that the family is one name
(`UNKNOWN`), and right that both `c_analyzer/info.py`'s boxed
`_misc.Labeled(...)` and `c_common/tables.py`'s `UNKNOWN = '???'` are
involved. Its diagnosis was incomplete: it named only the ROUTING defect
(a bare name resolving through the shared `_global_to_module`), which is
one of three, and the one that had already been fixed before this branch
started.

1. **Routing, bare `UNKNOWN`.** `_lower_IdentExpr` decided the name was
   ours and then asked the shared, whole-transitive-tree, name-keyed
   `_global_to_module` anyway — a "first module to claim this bare name
   wins" table, so it answered `c_common.tables`. Read and write landed
   on two different slots. The WRITE side already used
   `gen._current_module_ctx` at every site; this is the read half.

2. **Type, bare `UNKNOWN`.** `_own_overlay_global_ctype`'s rule 2 narrows
   "a foreign homonym's pointer cdecl must not re-type this module's own
   SCALAR conclusion". Its exact mirror for a CONTAINER own-conclusion was
   missing, and is not reachable by narrowing: a container conclusion
   (`MojoList *`) falls *past* rule 2 (own is not a scalar) into rule 3,
   which deferred to ANY shared cdecl. `tables.py`'s `'char *'` therefore
   re-typed `info.py`'s own boxed container, and `_global_dst_ctype` (the
   assignment sites) coerced the RHS to `char *` against an already-frozen
   `int64_t` field. New rule 4 boxes a non-dispatch container conclusion
   to `int64_t` whenever the shared cdecl is not itself a container
   pointer.

3. **Type, qualified `tables.UNKNOWN`.** `_lower_MemberExpr`'s
   `submod.GLOBAL` branch resolved the FIELD module-correctly but took
   both halves of the TYPE from the shared name-keyed dicts — and
   `_global_to_module`, itself such a dict, GATED the branch, so only
   whichever module was scanned first was reachable through the qualified
   spelling at all. New `_module_global_field_type` reads the owning
   module's own `_module_globals` `(name, c_type, g_mtype)` triple, which
   is exactly what the struct typedef, the initializer and the
   `_<mod>_mojo_global_get_<name>` accessor were generated from, so the
   read agrees with the field by construction rather than by a second
   independently-drifting inference.

Regression test `same_bare_name_global_reads_own_module_slot` in
`test_gimple_runner.py` — a package with a string `MARKER` in `tables.py`
and a list `MARKER` in `main.py`, printing BOTH `MARKER` and
`tables.MARKER` side by side and comparing against CPython on the same
files. Verified failing on the pre-fix tree (gcc `-Wint-conversion`) and
passing after. Its fixture is the smallest case that reaches all three
defects at once, which is why it asserts on the built binary's stdout and
not merely on a successful compile.

**One correction to the doc's own reasoning, recorded because it changes
what a follow-up should do:** the doc says these ten errors "belong to
another worker's claim" and that `bugs/hard/CODEGEN_same_bare_name_struct_
collision_across_modules.md` "correctly predicts the symptom". The
prediction was right; the ownership was not load-bearing. No other worker
holds this area now, and the defect was three ordinary layering bugs in
one name, fixable without touching the struct-collision machinery.

### What still blocks this file — three UNRELATED shapes, none of them `UNKNOWN`

Same three imported modules the previous entry listed, still failing first:

```
# ERROR: compiling imported module 'c_parser.info'  -> next(...) on next(CallExpr) has no lowering
# ERROR: compiling imported module '._func_body'     -> cannot coerce MojoDict * to MojoList *  value='_t513' dest='data'
# ERROR: compiling imported module 'c_parser.match'  -> cannot coerce MojoSet * to MojoList *   value='_t6' dest='expected'
```

Two notes that are new since the previous entry:

* `c_parser.info`'s refusal CHANGED. It used to be `cannot materialize a
  generator as a list: no known generator API for 'rendered'`; it is now
  an honest `next(<CallExpr>)` refusal, which is the same
  `_func_body`/`match` shape as a link-time hazard turned into a
  compile-time one. Neither is this file's own error, and both are
  tracked in `bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`.
* A FOURTH module now appears that the previous entry did not list:
  `.iterutil` (`next(...)` on `next(IdentExpr)`). It is in the same
  closure and is the same refusal class.

So: this file's own gcc errors are fixed; its remaining floor is three
(soon four) imported-module shapes, all in other docs.

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
