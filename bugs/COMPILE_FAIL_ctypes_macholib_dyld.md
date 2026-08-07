# COMPILE_FAIL: Lib/ctypes/macholib/dyld.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/macholib/dyld.py`

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

With the arity error out of the way, this file's actual `mojo.py build`
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
