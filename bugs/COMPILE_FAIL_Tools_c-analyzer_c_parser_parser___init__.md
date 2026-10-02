# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-09-30 — one gcc blocker fixed; this file is still far from building (three imported modules fail first)

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`).

### What this session fixed

The file's own gcc errors went from THREE to TWO, because one of them was a
cross-module mangled-symbol mismatch and is now gone (commit `b88c3dce`):

```
was:  _compound_decl_body.py:17:10: error: implicit declaration of function
        '_common_set_capture_groups_37bd8e'; did you mean
        '_common_set_capture_groups_6aabcf'? [-Wimplicit-function-declaration]
now:  (gone)
```

Root cause, in one line: `_local_def_pts` published each DEFINING module's
committed signature into the shared `_home_def_param_types` registry under
`module_name.replace('.', '_')`, which spells the relative-import module
`._common` as `__common`, while every IMPORTER resolves the same module as
`_common`. The registry read therefore always missed and fell through to a
fallback whose parameter types are all `int64_t` — a different overload hash
from the one the definition emitted. Only modules with BOTH a leading depth
dot and their own leading underscore are affected, which is why it read as
intermittent. The string rule lived in four near-identical private copies,
two of which omitted the leading-dot strip; they are now one
`module_qualifier` in `mojo/middle/module_shared.py`. Regression:
`relative_underscore_module_mangled_suffix_agrees` in
`test_gimple_runner.py` (a package build, run, compared against CPython).

### What is still in front of the file — read this before starting

**The two remaining gcc errors are a SYMPTOM, not the blocker.**

```
_common.py:50:9: error: implicit declaration of function 'parser__regexes__ind_15d274'
_common.py:50:7: error: assignment to 'char *' from 'int' makes pointer from integer without a cast
```

`_common.py:50` is `_PAREN_RE = re.compile(rf'''... {_ind(STRING_LITERAL, 3)} ...''')`.
The call is emitted as `parser__regexes__ind_15d274` — the qualifier is
RIGHT — but no declaration and no definition of that symbol exists anywhere in
the generated unit, because `c_parser/parser/_regexes.py` contributed NO code
at all: its `__parser__regexes_toplevel` is declared and called but never
defined, and its one function `_ind` is absent. That module compiles fine on
its own (`fire.py build .../parser/_regexes.py` succeeds, `_ind` present 37
times in the `.c`).

It contributes nothing HERE because it is reached through a chain whose
middle link fails and is rolled back:

```
# ERROR: compiling imported module '..info' from .../c_parser/info.py:
    cannot materialize a generator as a list: no known generator API for 'rendered'
# ERROR: compiling imported module '._func_body' from .../parser/_func_body.py:
    cannot coerce MojoDict * to MojoList * (incompatible container kinds)
```

`_compile_imported_module`'s `except` handler rolls back `_compiled_modules`,
structs, ptr helpers and inline defs for the failed subtree — but explicitly
NOT `_module_globals` / `_module_global_inits`, which is why the root still
emits `extern struct __parser__regexes_toplev` and still CALLS
`__parser__regexes_toplevel()` in `main()` while the module's own body was
discarded. That is a link-time undefined symbol waiting behind the
compile-time ones, and it is the real shape of this bug: a failed submodule
leaves dangling references to a subtree that was thrown away.

### Next step, in order

1. **`c_parser/info.py`** — `cannot materialize a generator as a list: no known
   generator API for 'rendered'` (`mojo/backend_gimple/emit_infra.py:2418`).
   The site is `HighlevelParsedItem._data_as_row`:
   `rendered = cls._render_data_row_item(...)` then `rendered, = rendered`,
   where `_render_data_row_item` returns `cls._format_data('row', data, extra)`
   and `_format_data` IS a generator. So `rendered` legitimately holds a
   `MojoGenerator *`, and `a, = b` on a generator means "take its first
   yielded value". The ordinary path types the local correctly but never
   records the api: `_generator_var_api` is populated for a bare-name compiled
   generator call (`_emit_generator_start_call`, `emit_calls.py`) and for a
   function that RETURNS a generator (the `_fn_returns_generator` block,
   `emit_calls.py:5378`) — neither covers a call to a compiled GENERATOR
   METHOD through `cls.`, nor a method that returns one. Fixing it needs the
   `cls.<genmethod>(...)` construction (`__mgco_<Struct>_<method>_start`,
   already registered in `_generator_method_api` — `cpp_core.py:5373` reads it
   for the coroutine path, the ordinary path does not) AND the
   method-returns-a-generator counterpart of `_fn_returns_generator`.
2. **`c_parser/parser/_func_body.py`** — `cannot coerce MojoDict * to MojoList *
   ... value='_t513' dest='data'`. A destination named `data` typed
   `MojoList *` receiving a dict. Not root-caused; start from the emitted
   `_t513`.
3. **`c_parser/match.py`** — `cannot coerce MojoSet * to MojoList * ...
   value='_t6' dest='expected'`. Not root-caused either, but probably the same
   coercion-chokepoint family as (2) and worth fixing together with it.
4. Then re-check whether the dangling `__parser__regexes_toplevel()` call
   survives. That is the assertion that (1)-(3) actually cleared the floor
   rather than just moving the error.

Do NOT start with the `_ind` / `parser__regexes__ind_15d274` gcc error. It is
downstream of (1); fixing it directly would mean special-casing a symbol that
should not be dangling at all.

