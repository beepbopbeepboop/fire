# COMPILE_FAIL: Tools/c-analyzer/c_parser/parser/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/parser/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-29 — the companion's constructor-call lowering landed; 11 g++ errors are 8

Re-measured from a copy of the upstream tree (`.tmp/ca/` from
`Python-3.14.6/Tools/c-analyzer/`, `python3 fire.py build -o .tmp/out/r3
.tmp/ca/c_parser/parser/__init__.py`, arm64). The C side is unchanged
and clean; the build's rc=1 is still the C++20 companion `__init___gen.cpp`.

### What landed

The companion's struct-constructor call (`SourceInfo(filename)` inside
`_iter_source`) lowered its arguments verbatim, so the omitted defaulted
`_current=None` reached g++ as a call with too few arguments, and a field read off the
constructor result (`Box(2, 10).x`) used `.` on a `Struct *`. Two fixes in
`mojo/backend_gimple/cpp_core.py`:

1. The constructor branch of `_cpp_expr` now pads its arguments through the same
   `_cpp_pad_struct_method_call_args` helper every struct-method call branch already
   uses, so the trailing default is filled from the declared `__init__` signature.
2. The guard `StructName(args)` (`fname in struct_field_types`, has `__init__`, no
   kwargs) is `_cpp_is_struct_ctor_call`, shared by the constructor branch and by the
   attribute-read fallback, which emits `->` for a constructor result.

Regression: `test_gimple_generator_runner.py::generator_struct_ctor_fills_a_trailing_default`
(in `run_ctor_default_arg_in_generator_tests`). It is a package fixture (`box.py` is
now in `_FOREIGN_PKG_FILES`): a consumer with `*, start=[]` is forced onto the cpp path,
and `Box` is imported from a sibling module as `SourceInfo` is in the real case. The
single-file shape does NOT reach the cpp path (the suite's A3 backend takes simple
generators), so a single-file test would pass before and after; this one fails before
the fix (`too few arguments to function 'box_Box___init__'` and `request for member 'x'
... of pointer type 'Box*'`) and passes after, verified by reverting the `cpp_core.py`
hunk and restoring it.

### Measured: before → after

* `__init___gen.cpp` g++ errors: 11 → 8. The `:149:167` (too few arguments), `:149:172`
  and `:149:195` conversions on the `_info_SourceInfo___init__` call are gone from the
  list (line `:149` now has one error, at `:149:219`).
* C side: unchanged, clean. Imported-module floor unchanged (`.iterutil`'s `next(...)`,
  `..info`'s `rendered, = rendered`).

### What is still open, in the order it appears in the companion

1. `__init___gen.cpp:149:219` — `invalid conversion from 'SourceInfo*' to 'int64_t'`:
   a struct pointer stored into `allinfo` (a dict) through an int64 slot in the
   companion's dict-store lowering.
2. `:165`–`:169` — `filename = ({0, 0, 0})[0]` / `lno = ({0, 0, 0})[1]` /
   `text = ({0, 0, 0})[2]`: the `for fileinfo, line in lines` target and the
   following tuple unpack are emitted as placeholders, plus `expected ';' before '}'`
   on each. This is the "tuple target" half of the companion's generator-body
   lowering; the generator body also still carries `0;` / `while (0)` /
   `if (0)` for several method-call statements (`srcinfo._add_line`,
   `srcinfo.too_much`, `srcinfo._used()`), i.e. the body lowering stubs whole
   statements to `0` (`_debug_note` "stubbed operation") and this is the real size of
   the feature. Confirm with `_debug_note` output before choosing an order.
3. `:171:28` — `char*` → `int64_t` on the `text` slot (same tuple-target family).
4. The two imported-module floors (`.iterutil`, `..info`) are unchanged; they still
   decide whether `_iter_source`'s module compiles at all under the full import chain.

Next step: (2) first — the `for`/tuple target lowering in the companion, since it
accounts for six of the remaining eight errors (`:165`–`:169`) and the stubbed statements
are the same family. Do not start from the `:149` dict-store error; it is downstream of the same
generator body.

## Status 2026-10-23 — the `_ind` pair is GONE (the failed-attempt rollback landed); the new first error is a proven pre-existing companion `.cpp`

Re-measured the c-analyzer cluster from the copied tree (`build/remes/ca/`, `python3
fire.py build -o build/remes/out/r16 .../c_parser/parser/__init__.py`, arm64, warm
CAS). The 2026-10-04 entry's diagnosis — "the honest next step is the roll-back, not
the registry" — is in the tree, and it closed the pair.

### What landed

`_compile_imported_module`'s `except` handler (`mojo/backend_gimple/emit_resolve.py`)
now rolls back what a FAILED imported-module attempt added:

1. **Its guard entries in `_compiling_file_paths`** — the set was add-only, so a
   failed attempt left every path it had compiled (including its own nested imports)
   permanently marked, and a later import of the same file under a sibling spelling
   was silently REFUSED and "compiled with nothing" — the guard-REFUSAL half of the
   poisoning this doc's 2026-09-30 entry described.
2. **The attempt's tail of `gen._sub_toplevels`** — the handler carried a snapshot
   that was never used, so the failed attempt's toplevel records leaked into the
   root's emission: `extern struct __parser__regexes_toplev` plus a
   `__parser__regexes_toplevel()` call in `main()` whose body was discarded (the
   dangling-reference half, seven dangling toplevels in master's C).
3. **Its spelling-CLAIM registry keys** (`_imported_func_home`,
   `_imported_struct_home`, `_inline_module_qualifiers`) — claims named by a
   spelling whose compilation was discarded are false. The SIGNATURE registries are
   deliberately NOT rolled back: their values are spelling-isolated (each winning
   spelling publishes under its own key), and they are the only signature source for
   units that compile before the definer's own successful attempt.

### Measured, this entry, master vs fixed (both single-TU `.__init__.build/__init__.ci`)

* master: ONE call site `parser__regexes__ind_15d274` (the corpse suffix,
  (int64_t,int64_t,char*)) with no declaration and no definition anywhere in the
  unit, plus **seven dangling toplevels** (`__parser__regexes_toplevel`,
  `_c_common_toplevel`, `_c_common_clsutil_toplevel`, `_c_common_fsutil_toplevel`,
  `_c_common_strutil_toplevel`, `_c_common_tables_toplevel`, `_logging_toplevel`).
* fixed: `_ind` is unified on `_regexes__ind_0f1876` across the whole TU — one
  forward declaration + one definition + 33 call sites — including the
  `_common.py:50` site both errors in this doc point at, which now reads
  `STRING_LITERAL` through `___regexes_globals` (the owning module's globals — the
  2026-10-04 entry's Step-1 gate), calls the correctly-typed
  `char *(char *, int64_t, char *)` definition, and keeps the `mojo_str_cat` chain
  in `char *`. **Zero dangling toplevels** (the six called are exactly the six
  defined), and the dead-subtree sections of the discarded `c_common` modules are
  gone.
* The C-side `.ci` now compiles CLEAN; the build's rc=1 is exclusively the C++20
  companion: 11 g++ errors in `__init___gen.cpp`'s `_mojogen__iter_source_impl` —
  the missing default-argument fill of `_info_SourceInfo___init__` (`:149:167`),
  the `({0,0,0})[N]` tuple-unpack placeholders read as `int[int]` (`:165-169`),
  the pointer/integer comparison (`:141:35`) and the two int64/char* conversions on
  the same line. Proven PRE-EXISTING, not a regression of the rollback:
  regenerating the companion on master and on the fixed tree (cp-swap of the single
  changed file) yields a BYTE-IDENTICAL `__init___gen.cpp` (diff rc=0). It is the
  companion emitter's residue around the `_iter_source` generator
  (`c_parser/parser/__init__.py:167-204`) — feature-sized, the same project the
  `gimplegenerators` suite is chasing. The import floor is unchanged and is two
  honest content refusals: `.iterutil`'s `next(...)` on a `MojoList *` receiver,
  and `c_parser.info`'s `rendered, = rendered` ("cannot materialize a generator as
  a list: no known generator API for 'rendered'").

### Regression

`test_link_mode.py::test_failed_import_attempt_does_not_poison_later_spelling` —
the minimal mirror of the measured shape: a poison module that fails on the
deterministic `.iterutil`-shape refusal (`items = iter(items); next(items)` on a
`MojoList *` receiver — a content refusal that fires identically on master and on
the fixed tree, so the only thing the fix changes is what the failure LEAVES
BEHIND), whose nested import plants the guard entry on a shared file, and a sibling
in a different package that imports the shared file under the sibling spelling. On
`566ba1c9` (master) the leftover guard entry REFUSES the sibling import and its
call site emits `implicit declaration of 'shared_s_...'` plus `assignment to
'char *' from 'int'` — build fails, no binary. On the fixed tree the attempt rolls
its state back, the sibling compiles for real, and the binary prints `s X!` like
CPython. Verified through the suite's own `driver.compile_program` path, fails
before / passes after.

### Next step, in order

1. **The companion `.cpp` emitter for `_iter_source`** (feature-sized, proven
   pre-existing): the default-argument fill for the `SourceInfo.__init__` call,
   the `({0,0,0})[N]` placeholders, the pointer/integer comparison. Do NOT touch
   the C-side `_ind` path again — it is unified and measured; if a future edit
   splits the 35 `0f1876` references, that is the regression signal.
2. **Rows 13/14's new first error** — unmasked by this rollback, not caused by it:
   `conflicting types for 'info_get_default_storage_9f63a2'` (present IDENTICALLY,
   same line, same pair, in both the six-registry and the narrowed measurement —
   i.e. independent of the signature-rollback choice). Once `c_parser.info`
   actually compiles in the TU, its unannotated `def get_default_storage(decl)`
   gets a text-scan re-export extern (module_gen.py's `/* from .info */` block,
   typed from the scanner's int64 default) beside a definition typed from the body's
   own returns (`char *`). That is the "type-mismatch hazard" documented in that
   emitter's own comment; the `MojoTuple_` branch a few lines below already
   consults the definition-side store via `_func_return_type_for_call`, and
   extending that to the unannotated-return case is the shape of the fix.

## Status 2026-10-04 — EIGHT gcc errors are TWO, and the two that are left are the `_ind` pair this doc said to re-check last

Re-measured on this tree (`python3 fire.py build -o .tmp/out .tmp/ca/c_parser/parser/__init__.py`,
sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, arm64, ~8 s). The
complete `error:` list is now:

    c_parser/parser/_common.py:50:9: error: implicit declaration of function
      'parser__regexes__ind_15d274'
    c_parser/parser/_common.py:50:7: error: assignment to 'char *' from 'int'
      makes pointer from integer without a cast

and nothing else. Every error the 2026-10-02 entry listed besides that pair is GONE, and
it is worth saying which is which, because the entry's own next step ordered them:

* **Step 1 is already in the tree** — the bare-name global read does consult the module's
  OWN field list first, in three documented steps (`emit_exprs._lower_IdentExpr`'s
  `_module_global_field_type(_read_mod, name)` → the recorded import home → the owner),
  and its GATE refuses the whole `_<mod>_globals.<name>` read when this module has no field
  for the name and no recorded home. That gate is why `'struct ___common_toplev' has no
  member named '_logger'` (three sites), `'STRING_LITERAL'` and `'_func_body`'s
  `'DECL_BODY_PARSERS'` no longer appear: the names are read as something else rather than
  off a struct that does not declare them.
* **Step 2 is fixed** — `mojo_mark_dict_bool_values` does not exist in the runtime and no
  emitter calls it, so `_global.py:125` cannot be an implicit declaration any more. The five
  producer sites that used to emit it were consolidated into `emit_infra`'s
  `emit_dict_int_value_store`; confirmed by grep (`mojo/backend_gimple/emit_exprs.py`,
  `emit_stmts.py`, `emit_infra.py`, `runtime/`: prose comments only) and by the
  compiled-vs-CPython case `gimple_dict_of_bool_values` /
  `gimple_dict_store_shapes_share_one_bool_slot` in `test_gimple_runner.py`.
* **Step 3 was the right thing to re-check and it is what is left.** The `_ind` pair is a
  dangling reference to a module whose body was thrown away, not a field-registry problem:
  `c_parser/parser/_regexes.py` compiles fine alone (`_ind` present 37 times in its own
  `.c`).

The imported-module floor is unchanged and is two modules, both `next(...)`:

    # ERROR: compiling imported module '.iterutil' from .../c_common/iterutil.py:
      `next(...)` on next(IdentExpr) (receiver typed `MojoList *`) has no lowering
    # ERROR: compiling imported module '..info' from .../c_parser/info.py:
      `next(...)` on next(CallExpr) (receiver typed `int64_t`) has no lowering

**So this file's own gcc errors are down to the pair, and the honest next step is the
roll-back, not the registry.** `_compile_imported_module`'s `except` handler rolls back
`_compiled_modules`, structs, ptr helpers and inline defs for the failed subtree but
explicitly NOT `_module_globals` / `_module_global_inits` — which is why the root still
emits `extern struct __parser__regexes_toplev` and still CALLS
`__parser__regexes_toplevel()` in `main()` while that module's own body was discarded. The
`next(...)` floor has to go first, and the `next(...)` floor is TWO shapes with two answers:

1. `iterutil.peek_and_iter` does `items = iter(items)` then `next(items)` — a REBOUND
   list-iterator local, which the compiler already supports elsewhere. This is the cheaper
   of the two and is adjacent to
   `bug:CODEGEN_next_on_bound_list_iter_cursor_off_by_one` (another worker's claim), so the
   first move is to read that doc's measurement rather than re-derive it.
2. `c_parser/info.py`'s `rendered, = rendered` is `next(<a call returning a generator>)` —
   a different question, and `c_parser/info.py`'s own doc entry carries its detail.

One more measurement, because it is in this closure and it is the `next(...)` floor's
SIBLING: `c_parser/preprocessor/__init__.py` used to contribute ~17 gcc errors of its own,
including six `expected ')' before ',' token` and `'i'`/`'v'` undeclared at its two
`for i, in _resolve_file_values(...)` / `[i for i, in _resolve_file_values(...)]` lines.
Seven of those are still there and the trailing-comma ones are GONE, because a `for`/
comprehension target over a generator that yields ONE value now binds the target's single
NAME instead of declaring the target's own spelling (`(i,)`) as a C variable — fixed on
this tree, regression in `test_gimple_generator_runner.py`'s
`gen_one_slot_tuple_target_binds_one_name`. What remains there is `source_good_file`
called with two arguments (a callable-valued-parameter signature), a `MojoList *` into an
`int64_t` at :69, four result locals never declared at :123-129, and
`c_common_fsutil_match_glob_2dbb98` vs `..._c2eb2a` at :191 — that last one is the
mangled-suffix family `b88c3dce` fixed for `_common`, so it is worth checking whether
`c_common.fsutil` reaches the same spelling before treating it as a new defect.

## Status 2026-10-02 — the two gcc errors this doc named are GONE; what is left is ONE root cause, and it is the self-host doc's `_module_globals` lead

Fresh `python3 fire.py build -o .tmp/out/ca/p
.tmp/ca/c-analyzer/c_parser/parser/__init__.py` on `ad7ffd96` (sources
copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`), arm64.
Eight `error:` lines, all in TWO files, and every one of them is the same
shape:

```
c_parser/parser/_common.py:16:27   'struct ___common_toplev' has no member named '_logger'
c_parser/parser/_common.py:18:27   'struct ___common_toplev' has no member named '_logger'
c_parser/parser/_common.py:25:27   'struct ___common_toplev' has no member named '_logger'
c_parser/parser/_common.py:50:26   'struct ___common_toplev' has no member named 'STRING_LITERAL'
c_parser/parser/_common.py:50:7    assignment to 'char *' from 'int' makes pointer from integer without a cast
c_parser/parser/_common.py:50:9    implicit declaration of function 'parser__regexes__ind_15d274'
c_parser/parser/_func_body.py:81:31 'struct ___func_body_toplev' has no member named 'DECL_BODY_PARSERS'
c_parser/parser/_global.py:125:3   implicit declaration of function 'mojo_mark_dict_bool_values'
```

### Both blockers this doc's previous entry listed are cleared

* Its item 1, `c_parser/info.py`'s "cannot materialize a generator as a
  list: no known generator API for 'rendered'", is gone — and it needed no
  fix here: `_generator_method_api` and the method-returns-a-generator
  counterpart now both exist, so `cls.<genmethod>(...)` is drivable.
  Measured directly before starting: `rendered = self._gen(x); a, = rendered`
  compiles and runs for an instance method, a bare-name "classmethod", and
  a real `@classmethod` (`r = cls._fmt(v); a, = r` prints 42 in all three).
* Its items 2 and 3, `cannot coerce MojoDict * to MojoList *` in
  `_func_body.py` and `cannot coerce MojoSet * to MojoList *` in
  `match.py`, are gone as well — no coercion error remains in this file's
  closure.

### The one root cause, measured rather than guessed

`___common_toplev` is `_<_c_field_name('._common')>_toplev`, and the struct
it names is emitted WITH fields — `VAR_DECL`, `_PAREN_RE`, `re` — just not
with `_logger` or `STRING_LITERAL`. So this is not the "no field row at
all" case the previous entry described; it is a name that IS a global of
`._common` by the bare-name read's own gate and is NOT a field of the
struct the same module emits.

Which half is wrong is decidable from the code:

* the WRITE side registers into `_module_globals[current_mod_name]`
  (`module_gen.py`'s module-globals pass) and the struct is emitted from
  `_module_globals[mod]` a few lines later (`gen_module_impl`'s
  `_<mod>_toplev` block);
* the READ side (`emit_exprs._lower_IdentExpr`'s bare-name global branch)
  decides "this name is a global of THIS module" from the SHARED,
  whole-transitive-tree, name-keyed `_global_var_types` /
  `_global_to_module` / `_own_overlay_global_ctype`, and then emits
  `_<mod>_globals.<name>`.

`_logger` is a FUNCTION-SCOPED `from . import _logger` inside
`c_parser/parser/_common.py`'s `log_match`, bound as a VALUE; that is a
name in `_global_var_types` that no module-globals pass ever registers, so
the gate passes and the field does not exist. Same for the
`STRING_LITERAL` import and `_func_body`'s `DECL_BODY_PARSERS`. This is
the same family as `bugs/CODEGEN_selfhost_red_on_the_merged_tree_149_gcc_
errors.md`'s `has no member named 'TEST_PATH'` / `'_module_loader'` half,
one module smaller and therefore directly observable.

### Next step, in order

1. **Make the bare-name read consult the module's OWN field list first.**
   `gen._module_global_field_type(gen.module_name, name)` is authoritative
   and already exists (it is what the qualified `submod.NAME` half uses,
   and what `_cpp_module_global_field` in this branch's `cpp_core.py` now
   uses); if it answers None, the name is not a field of this module's
   struct and a `_<mod>_globals.<name>` read is wrong whatever the shared
   tables say. This can only remove errors, never add them: today every
   name the authoritative list rejects is already a gcc error. The same
   registry is the one `_cpp_module_global_refs` keys the .cpp mirror off
   (commit `12106a4b`), so the two sides agree by construction once this is
   done.
   **Do this before anything else**: it is small, it is testable on this
   one file, and every remaining error here is downstream of it.
2. `mojo_mark_dict_bool_values` (`_global.py:125`) is a separate defect
   with its own trail in this repo (`mojo/backend_gimple/emit_stmts.py`'s
   dict-bool marking, and the same name in the self-host doc's error set).
   Trace it after (1), when the rest of this file is down to it.
3. `parser__regexes__ind_15d274` (`_common.py:50`) is the previous
   entry's item 1 residue — `c_parser/parser/_regexes.py` contributes no
   code because its own compile is discarded. Re-check it AFTER (1): the
   dangling reference it is part of may be a consequence of the same
   field-registry gap rather than a separate one.

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

