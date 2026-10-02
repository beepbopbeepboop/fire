# COMPILE_FAIL: Lib/ctypes/macholib/dyld.py

## Status (2026-09-30, branch work/compile-fail-stdlib-misc — THREE refused generators down to ONE, and its own compile unit has been clean for several rounds)

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py`
(119 s, peak 0.4 GB). `macholib/dyld.py` and `macholib/framework.py`
contribute **zero** `error:` lines — the whole-program build is now
refused by a single module-level generator refusal, and it names ONE
function instead of three:

```
cannot compile module: function(s) dyld_default_search (generator
function(s), contain a `yield`/`yield from`) ...
Unsupported shape(s): dyld_default_search: every `yield` must carry a
value, and all values must agree on one scalar type
(int64_t/double/_Bool).
```

`dyld_executable_path_search` and `dyld_override_search` are no longer in
the refused set at all; `dyld_image_suffix_search` (the closure `_inject`
generator) is not either. So the 2026-08-06 five-bullet cluster below is
confirmed resolved in full, and the remaining blocker is one function's
yield-slot agreement, not a corpus.

`dyld_default_search`'s own yields are `name`, `os.path.join(path,
framework['name'])` and `os.path.basename(name)` — all strings in real
Python. The reason it cannot be typed is the same shape as the
`_convert_egg_info_reqs_to_simple_reqs` gap in
`bugs/COMPILE_FAIL_importlib_metadata___init__.md`: the element type of
`framework['name']` (a subscript of a value returned by a foreign
`framework_info`) is not threaded into the generator body's yield-slot
inference, so `_generator_yield_ctype` cannot pin one scalar type and
refuses honestly rather than miscompiling. Feature-sized (struct-typed
subscript element typing through a cross-module return), deliberately NOT
attempted.

Doc kept open on that one generator.

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py`

## Status (2026-08-26, wtOpencode_dyld): FOUR shared codegen fixes landed — total closure errors 167 → 102; dyld.py's own unit still ZERO errors; end-to-end rc=1 remains, now blocked ONLY by other docs' tracked hard-bug classes

Re-verified fresh under the safety-wrapped watcher (build completes in
~2 min, well within budget). dyld.py's own compile unit still
contributes zero `error:` lines (only the harmless unused-variable/
unused-label warnings). The super()/self.__class__ and other
recently-landed shared mechanisms were already sufficient for dyld.py
itself — no regression there. What this session DID fix is four
genuine shared-mechanism bugs hit by the transitive closure, each with
a standalone minimized repro:

1. **Cross-module same-bare-name homonym poisoning of call-site arity
   padding** (commits 55ac8f9 + follow-ups). re/_compiler.py's three
   recursive `_compile(code, pattern, flags)` statement calls were
   padded to FIVE arguments with **codeop.py's** unrelated homonym's
   trailing defaults (`incomplete_input=True, *, flags=0`): GCC "too
   many arguments to function '__compiler__compile_132aaf'; expected 3,
   have 5" ×20 whenever both modules share a whole-program closure —
   i.e. always, for any ctypes build. Two coupled root causes: (a) the
   ExprStmt-level general-call path read expected_params from the
   oscillating shared bare-name `func_param_types` slot directly,
   missing BUG-2026-024's tiered `_effective_param_types` lookup that
   `_lower_named_call` already had; (b) gen_module's all-functions
   registration loop keyed `_func_param_defaults`/`_func_kwargs_slot`
   by `_func_csym(s.name)` which resolves by BARE name, so a foreign
   homonym registered its defaults under THIS unit's own def's mangled
   key. Fixed by (a) tiering the twin identically and (b) guarding
   registration by identity against `_local_def_nodes`. NOTE for future
   sessions: a tier-SHAPE probe at that registration point was tried
   and REVERTED — consulting `_effective_param_types` there freezes
   `_local_def_pts`' lazy memo at unsettled pre-Pass-1.x inference
   shapes and regresses `_emit_call` coercion across typing.py's
   `_type_check` callers ("makes pointer from integer"); identity check
   only.

2. **Shared funcptr marks leak out of aborted module compiles**
   (cf39248). A module whose gen_module raises mid-compile
   (collections/inspect's deliberate subscript-store fallback) has
   usually already run its preamble-assembly pass, marking every
   builtin-as-value funcptr name into the SHARED
   `_emitted_funcptr_builtins`, while its generated text is discarded.
   Later modules referencing the same name then compute
   `needed − emitted == ∅` and emit no declaration:
   "'_funcptr_mojo_len' undeclared" at re/_compiler.py:42 (`_len =
   len`), re/_parser.py:520, textwrap.py:303 (`sum(map(len, ...))`).
   Fixed by adding the funcptr pair to `_compile_imported_module`'s
   existing rollback-on-failure block.

3. **Struct `__getitem__` on a void-typed method returned ('void', '')**
   (e3be51f). A raise-only `__getitem__` body (_collections_abc.
   Mapping's abstract `raise KeyError`) correctly infers a void C
   signature, but the subscript-read dispatch handed back an empty
   pair, so value-consuming contexts synthesized `void _tN;` +
   `_tN = ;` — "variable or field declared void"/"expected expression
   before ';'" ×22 in _collections_abc.py alone (Mapping.get,
   MutableMapping.update, Sequence index paths). Reads now yield a
   typed zero placeholder (unreachable at runtime); `__setitem__`
   stores keep the discarded pair. _collections_abc.py now compiles
   with ZERO errors.

4. **Bare POSIX calls had no prototype source** (85b4ed5). os.py's own
   wrappers call `mkdir/rmdir/execv/execve/fork/unsetenv` as BARE names;
   nothing recorded prototypes for plain unrenamed libc calls →
   "implicit declaration" + pointer-coercion mismatches, 9 errors.
   Added `_ensure_libc_self_extern` (shared by `_lower_named_call` AND
   the ExprStmt twin), pinned `_LIBC_SIGS` entries, and `execve` in
   `_NEEDS_SELF_EXTERN`. NOTE: do NOT add 'unsetenv' to
   _NEEDS_SELF_EXTERN — <stdlib.h> IS in the prelude and a self-emitted
   `int unsetenv(char *)` conflicts with its `int unsetenv(const char
   *)`, spreading "conflicting types" across every preamble section
   (observed +15 errors before revert). os.py now compiles clean.

Per-module error counts vs the 167-error baseline this session started
from: argparse 29 (=29, see below), _collections_abc 22→**0**,
framework.py 11 (=11), posixpath 9 (=9), os.py 9→**0**, typing
17→8, pickle 9→8, re/_parser 8→7, gettext 4 (=4), functools 3 (=3),
re/_compiler 21→**0**, threading 2 (=2), locale 2 (=2), copyreg
3→2, traceback 1 (=1), subprocess 1 (=1), re/_constants 1 (=1),
annotationlib 1 (=1), _colorize 1 (=1), textwrap 1→**0**, plus
codeop/ast/dataclasses/warnings/tracemalloc/fnmatch/pprint/linecache/
struct/_compat_pickle/__future__/dylib.py all at **0**.

Quality gate after EACH fix (all clean): test_gimple.py 256/256,
test_module_cache.py 76/76, make check-selfhost clean, from-scratch
stdlib dylib rebuild 0 skips / 0 errors.

### Remaining blockers — all OTHER docs' tracked classes, not new gaps

- framework.py ×11 and posixpath×9: the ALREADY-DOCUMENTED hard
  bare-name-collision class
  (`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`)
  — `reprlib_Repr_repr*` undeclared in framework.py's unit; ntpath.py
  and posixpath.py BOTH lift same-named closures from their duplicated
  `expandvars` implementations (`expandvars_repl`,
  `_alloc_expandvars_repl_env`, struct `expandvars_repl_env`,
  globals `_varsub`/`_varsubb`) into colliding TU symbols. Same shared
  naming machinery; not attempted here per that doc's ownership and
  the standing warning about broad changes to it.
- argparse.py ×29: Python %-formatting whose operand is a DICT
  (`'%(prog)s: error: %(message)s\n' % args`) — `_lower_percent_format`
  handles literal-LHS tuple/single operands but not named-dict specs,
  and several sites have a non-literal LHS (the `_()` gettext call)
  boxed to int64_t besides, which needs a runtime percent-format
  helper rather than static lowering. Genuine feature gap, medium
  size, not forced this session.
- typing ×8 / pickle ×8 / re/_parser ×7: assorted pre-existing
  funcptr-dispatch-table and coercion residue, unchanged by this
  session's fixes.

## Status (re-verified 2026-08-25, wtOpencode_group3): unchanged — dyld.py's own compile unit still contributes ZERO errors

Fresh safety-wrapped `fire.py build`: rc=1 with **183 total `error:`
lines, ZERO matching `macholib/dyld.py`** — the file's own compile
unit remains clean (this session's shared fixes — coroutine-body
isinstance semantics, str split-family, statement-level fnptr-call
guard, generator-body isinstance runtime discrimination — are all in
areas dyld.py already compiled clean). All remaining errors are the
same transitively-imported modules' own documented failure classes.
Doc kept open per convention; nothing further to do against THIS
doc's scope.

## Status (re-verified 2026-08-25): unchanged; dyld.py's own compile unit still clean

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/macholib/dyld.py` fresh (full run, under this session's
safety-wrapped watcher, completed within budget) against current
master (past the struct-method cross-call scalar contract "Pass 1.3e",
generator-consumption-ordering fixed-point retry + defaults-aware arg
padding, `**kwargs`-forward slot-alignment fix, and coroutine-body
`int()`/`float()` builtin support landed since the 2026-08-24 entry
below). `python3 fire.py build` still exits 1 overall (315 `error:`
lines, up from ~300, same noise-level shift as `socket.py`'s doc), but
`grep "macholib/dyld.py:" | grep error` returns ZERO hits — the ONLY
line matching this file's own path is a harmless `warning: variable
'error' set but not used`. Confirms the 5-bullet generator-codegen
cluster this doc tracked remains fully fixed; the file's own compile
unit has no errors. All 315 remaining errors are in other,
transitively-imported modules with their own separate, already-tracked
failure classes (same as noted below). Doc kept open (file still
doesn't build end-to-end as a whole program), but nothing further to
do against THIS doc's own scope — whoever next touches this file
should look at the OTHER modules' failures.

## Status (2026-08-24): the whole 5-bullet generator-codegen cluster below is FIXED; file still doesn't build end-to-end, but only due to unrelated pre-existing gaps elsewhere in its dependency closure

Landed the `_cpp_trusted_fn_return_types`/`_cpp_fn_container_shape`
feature in `gimple_cpp_core.py` (coroutine-body local-variable/yield
typing derived from a callee's own inferred return ctype, plus a
static dict/list container-shape scan of module-level functions for
subscript lowering inside a generator body) — this directly targets
every one of the five bullets in the "2026-08-06" entry below. Re-ran
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/macholib/dyld.py`: **`dyld.py` (and `ctypes/macholib/
framework.py`) now compile with ZERO errors** — only harmless
unused-variable/unused-label warnings — where before the whole
`dyld_gen.cpp`/inline-C++-coroutine stage failed hard. Specifically
verified gone: `framework_info` no longer "not declared in this
scope" (sibling module-function calls now resolve via
`_cpp_trusted_fn_return_types`), `os.path.basename` no longer "'os'
not declared" and no more `begin()`/`end()` errors on `MojoList*`
iteration, `name.startswith`/`path.endswith` no longer fail on a
mistyped `int64_t` param, and no more `co_yield` int64_t/char*
conversion errors.

`python3 fire.py build` for this file still exits 1 overall, but the
remaining ~300 errors are entirely in OTHER, transitively-imported
modules with their own separate, pre-existing, unrelated failure
classes — `collections`/`inspect` (subscript-store fallback, benign),
`operator.py`/`copy.py`/`types.py`/`weakref.py`/`io.py`/`pickle.py`/
`argparse.py`/`enum.py`/`typing.py`/etc. Notably, some of these are
the ALREADY-DOCUMENTED, still-open bare-name-collision class
(`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
— e.g. `reprlib_Repr_repr*` "undeclared here" in `framework.py`'s own
compile unit, from `reprlib.Repr`'s dispatch table colliding with
another same-named symbol elsewhere in the transitive closure); none
of this is new, and none of it is generator/coroutine-codegen shaped.

Quality gate verified clean: `test_gimple.py` 252/252, `test_module_
cache.py` 76/76, `make check-selfhost` clean, from-scratch stdlib
dylib rebuild 0 skips (baseline 0, no regression).

Doc kept open (file still doesn't build end-to-end), but the specific
cluster this doc tracked is resolved — whoever next touches this file
should look at the remaining OTHER modules' failures, not this one.

## Status (re-verified 2026-08-23, triage pass): identical failure, all five generator-codegen bullets still reproduce

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/macholib/dyld.py`: fails at the same `dyld_gen.cpp` C++-coroutine
stage with the same error cluster — `'framework_info' was not declared
in this scope` (sibling module-level function called from inside a
generator body), `'begin'/'end' was not declared in this scope` (raw
range-for over `MojoList *`-returning calls and module-level list
globals), `'os' was not declared in this scope; did you mean 'cos'`
(module import not threaded into generator-body scope),
`request for member 'startswith'/'endswith' in ..., which is of non-
class type 'int64_t'` (untyped generator params defaulting to int64_t
instead of inferred `char *`), and the matching `co_yield`
`invalid conversion from 'int64_t' to 'char*'` errors. Nothing in this
cluster changed since the 2026-08-09 re-verification. Still five
maturity gaps in one shared codegen path (generator/coroutine
lowering), not a narrow fix: DOCUMENTED-NOT-FIXED — see the analysis
below for per-bullet detail.

## Status (updated 2026-08-06)

### 1. FIXED (commit d7a3043): nested-closure default params dropped at call sites

```python
def dyld_image_suffix_search(iterator, env=None):
    suffix = dyld_image_suffix(env)
    if suffix is None:
        return iterator
    def _inject(iterator=iterator, suffix=suffix):
        for path in iterator:
            ...
    return _inject()
```

```
error: too few arguments to function 'dyld_image_suffix_search__inject'; expected 2, have 0
```

Root cause: `gen_module`'s `all_functions` list (which feeds
`_func_param_defaults`, the table call sites consult to pad omitted
arguments with their real default value) only walks MODULE-LEVEL
`FunctionDef`s. A nested/closure `FunctionDef` like `_inject` above is
never in that list, so it never got a `_func_param_defaults` entry at
all — both closure-call lowering paths (`_lower_closure_call` for
expression context, and the `ExprStmt`-level closure-call branch) had no
default value to pad with when a call site (`_inject()`) omits arguments
relying on defaults, producing a hard "too few arguments" C error.

Minimally reproduced standalone:
```python
def outer(a, b):
    def inner(a=a, b=b):
        return a + b
    return inner()
def main():
    print(outer(3, 4))   # was: compile error; now: 7
main()
```

**Fix**: register each closure's `param_defaults` (keyed by its lifted C
name) in the existing closure-scan pass (gen_module's "Pass 3: collect
closures", where `ClosureInfo` objects are created), then have both
closure-call lowering paths pad missing args from there — mirroring the
free-function padding in `_emit_call`, but evaluating each default
expression via `self.lower_expr(...)` rather than the literal-only
`_default_expr_to_pair` used for top-level functions, since the
extremely common `iterator=iterator` idiom binds the OUTER function's own
live variable as the default, and code generation for the call site
happens while still inside that outer function's own body/scope.

Along the way, hit (and fixed) this exact function's own already-
documented self-host gotcha: the new comprehension's loop variable
(`_dv`) collided with an identical `_dv` used a few hundred lines up in
the same enclosing method (`gen_module`) for the top-level free-function
default registration — invisible to `test_gimple.py`/
`test_module_cache.py` (both stayed green), only surfaced as `make
check-selfhost` failing with `'_dv' undeclared`. Renamed to `_pn2`/`_dv2`
to resolve. This is the SAME bug class as the pre-existing comment a few
lines above in `_scan_for_closures` about not reusing `v` across two
comprehensions in one enclosing function — worth remembering as a
recurring gotcha whenever adding a NEW comprehension inside `gen_module`
(or any large method with many nested closures) that reuses a temp
variable name already used elsewhere in the same enclosing scope.

Full quality gate verified clean after the fix: test_gimple.py 247/247,
test_module_cache.py 76/76, make check-selfhost clean, from-scratch
stdlib dylib rebuild 0 skips, compile_stdlib.py -j8 664/664 0 unexpected.

### 2. NOT FIXED: generator/coroutine codegen gaps, now exposed by fix #1

With the arity error out of the way, this file's actual `fire.py build`
now proceeds into a totally different code path — `dyld_gen.cpp` (the
C++20-coroutine generator codegen), because `dyld_image_suffix_search`
(and several sibling functions: `dyld_default_search`,
`dyld_override_search`) contain `yield`. This exposes a substantial,
DISTINCT cluster of pre-existing gaps in that codegen path, none fixed
here — same general category as the already-tracked
`CODEGEN_generator_function_Lib_*.md` bugs (tasks #95-135), though this
specific file isn't one of those:

- **Untyped params inside a generator default to `int64_t` instead of
  their real inferred type** (`char *` for a string, `MojoList *` for a
  list) — e.g. `_inject`'s own `path`/`suffix` params, and
  `dyld_default_search`'s `name`, come through the C++ coroutine
  `yield_value(char * v)` overload as raw `int64_t`, hitting hard
  "invalid conversion from 'int64_t' to 'char*'" errors at every
  `co_yield`. The plain-C closure path (`_gen_lifted_closure`) already
  does real usage-based type inference for closure params
  (`ci.inferred_params`, gimple_codegen.py:19773-19791) — the generator/
  coroutine codegen path evidently does NOT reuse or replicate that
  inference for its own params.
- **Calls to sibling MODULE-LEVEL functions from inside a generator body
  aren't declared/resolved**: `framework = framework_info(name)` (called
  from inside `dyld_default_search`, a generator) — `'framework_info' was
  not declared in this scope'` in the generated `dyld_gen.cpp`, even
  though `framework_info` is an ordinary top-level function defined
  earlier in the same file and is NOT itself a generator.
- **`for x in <MojoList*-returning-call>:` inside a generator body doesn't
  get proper C++ range iteration**: `for path in
  dyld_framework_path_0c85c9(env):` — `'begin'/'end' was not declared in
  this scope'`. The plain-C path handles `MojoList *` iteration via
  runtime helper calls; the coroutine codegen instead emits a raw
  range-for over the call expression directly, which only works if the
  return type has real `begin()`/`end()` (it doesn't, for the codegen's
  own `MojoList *`).
- **Module attribute access (`os.path.basename(name)`) inside a generator
  body**: `'os' was not declared in this scope; did you mean 'cos'` — the
  `os` module import isn't threaded into generator-body scope at all.
- **String method calls on an untyped param inside a generator**
  (`name.startswith(...)`, `path.endswith(...)`) fail because the param's
  type defaulted to `int64_t` (see the first bullet) rather than
  `char *`, so the method-call lowering has no struct/string type to
  dispatch on: `request for member 'startswith' in 'name', which is of
  non-class type 'int64_t'`.

These are NOT independent one-off issues — they all trace back to the
same root observation: the C++ coroutine generator codegen path is
significantly less mature than the plain-C closure/function path for
ordinary Python idioms (typed params, calling sibling functions, string
methods, module attribute access, list iteration), even though the
core yield/coroutine machinery itself works (per the already-completed
"Compiled-path generator+async codegen project", commit history
2026-07-26). Not attempted here — this is a substantial cluster of gaps
across the generator codegen path, not a narrow fix, and deserves either
its own dedicated hard-bug investigation or grouping with the existing
#95-135 generator-function task cluster once one is picked up in depth.

### Re-verified 2026-08-09 against master `d3d4c68` — reproduces identically, no regressions/fixes in this cluster since 2026-08-06

Full rebuild (`python3 fire.py build .../ctypes/macholib/dyld.py`)
still stops at exactly the same `dyld_gen.cpp` compile stage, and every
one of the five bullets above still reproduces line-for-line against
the current generated `dyld_gen.cpp`:

- `framework = framework_info(name);` — still `'framework_info' was not
  declared in this scope'` (both in `dyld_override_search` and
  `dyld_default_search`).
- `for (auto path : dyld_framework_path_...(env))` /
  `dyld_library_path_...(env)` / `_root_globals.DEFAULT_FRAMEWORK_
  FALLBACK` / `_root_globals.DEFAULT_LIBRARY_FALLBACK` — still `'begin'/
  'end' was not declared in this scope'` at every generator-body
  `for`-loop over a `MojoList*`-returning call or a module-level list
  global.
- `os.path.basename(name)` — still `'os' was not declared in this
  scope; did you mean 'cos'`, at all three call sites.
- `name.startswith(...)` / `path.endswith(...)` — still `request for
  member 'startswith'/'endswith' in ..., which is of non-class type
  'int64_t'`, confirming untyped generator params (`name`, `path`,
  `suffix`) still default to `int64_t` instead of their real inferred
  `char *`/string type.
- Every `co_yield <string expr>` involving one of those mistyped params
  still fails with `invalid conversion from 'int64_t' to 'char*'` (or
  the reverse, `'const char*' to 'int64_t'` for `mojo_cstr_slice`'s
  start/stop args, which received a string where an offset int was
  expected — a downstream consequence of the same param-typing gap).

No part of this cluster overlaps with any fix landed since the
2026-08-06 update (checked `git log --oneline -85`: the intervening
generator-codegen fixes were the module-qualified free-function-symbol
collision fix (task #146, `bugs/hard/CODEGEN_generator_function_
symbol_not_module_qualified.md`) and the `len()`/`ord()` scalar-type-
estimator fix — neither touches generator-body param type inference,
sibling ordinary-function-call declarations, module-attribute-access
threading, or `MojoList*` range-iteration inside a coroutine body).
Confirmed still structural; not attempted here for the same reason as
before — this is five separate maturity gaps in one shared, large
codegen path (generator/coroutine lowering), not a single narrow spot.
