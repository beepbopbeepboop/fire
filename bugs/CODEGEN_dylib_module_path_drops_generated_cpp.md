# The dylib module compile throws away `generated_cpp`, so a generator in any dylib module silently loses its definitions

## Status

**Open. Root cause of the 2026-10-01 `mojoc` / `selfhost` / `bootstrap-stage2-cc`
red, which is fixed at the call site, not here.** One `@contextlib.contextmanager`
in `build_stdlib_dylib.py` was enough to make the whole self-host build fail to
link; it is now a class (commit `ccd83a2b`), and
`test_selfhost.py::closure_coroutines_are_lowerable` keeps the shape out. What
is left is the hole that let it through, which is much wider than one function
and is not fixed.

Not fixed here on purpose: the fix changes what every dylib module's compiled C
looks like (or adds a C++ object per generator-bearing module to the dylib link
line), which is a `make gate` change, and this was landed by a worker that is not
allowed to run one.

## The hole

`build_stdlib_dylib.compile_module_to_c` is the per-module compile that every
dylib build goes through — `_compile_one_object` → `_compile_module_job` →
`build()` — and `compile_stdlib.py` reaches the same function through
`compile_module_to_c_cached`. It runs:

```python
gen = GimpleGen(emit_entry_points=False, module_name=module_name)
gen._current_filename = path
box['c'] = gen.gen_module(Parser(py_tokenize(src)).parse_module())
...
return box['c']
```

`gen_module` fills a second artifact, `gen.generated_cpp`: the C++20-coroutine
translation unit holding the definitions of every generator / `async def` the
C++20 emitter accepted. Nothing reads it, and nothing can: it is not in the
return value, not in the CAS key, and not in `_compile_one_object`'s object
bytes. The module's `.c` still contains the four `extern` declarations and the
calls, so the object references

    _mojogen_<module>_<fn>_start / _resume / _value / _destroy

with nothing defining them anywhere on the link line.

Measured, on `build_stdlib_dylib.py` with a decorated generator in it:

    compile_module_to_c(...)                       -> 16920 lines of .c, no error
    gen.generated_cpp                              -> 6400 bytes
    g++ -std=c++20 -fPIC -Iruntime -c real_gen.cpp  -> exit 0
    nm -g real_gen.o | grep output_lock            -> T __mojogen_build_stdlib_dylib__output_lock_start
                                                      T __mojogen_build_stdlib_dylib__output_lock_resume

So the definitions are emitted correctly and compile cleanly. They are simply
never handed to anybody.

## Why it is silent in a dylib, and fatal in an executable

`build()` links the production dylib with `undefined=True`
(`-undefined dynamic_lookup`), so a module with dangling coroutine symbols still
produces a loadable dylib — those entry points simply do not work out of it, and
a client falls back to source. Nothing reports it. `stdlib-dylib`'s `skip` count
does not move and `stdlib-syntax` (which only checks that the `.c` parses) stays
green, so both of the verdicts CLAUDE.md singles out for before/after comparison
are blind to this class by construction.

An EXECUTABLE link is not blind to it. `fire.py build fire.py` goes through
`driver.compile_program`, which links `mojoc` against that dylib with every
symbol resolved, and the undefined coroutine entry points are collected straight
into the program's undefined set — which is the reported failure:

    Undefined symbols for architecture arm64:
      "__mojogen_build_stdlib_dylib__output_lock_start",
      "__mojogen_build_stdlib_dylib__output_lock_resume"
    collect2: error: ld returned 1 exit status 1

The two other build paths are worth separating, because they are NOT affected the
same way and it matters for the fix:

  * `fire.py build_executable` (what `test_selfhost.py` drives) inlines the whole
    closure with `do_imports=True` and compiles each imported sibling's
    `generated_cpp` — `_compile_imported_module` → `_compile_link_inline_cpp_unit`
    (`mojo/backend_gimple/emit_resolve.py:912`), gated on nothing. So the inline
    path has had a 4th coroutine-code source since
    `COMPILE_FAIL_Tools_cases_generator_parser.md`.
  * the dylib path has no equivalent, and `compile_module_to_c` does not even run
    `gimple_gen_coro.lower` / `desugar_genexps` / `_check_ownership` the way
    `gimple_codegen._run_pipeline` does — it calls `gen_module` on freshly parsed
    statements. That is a second, independent divergence between the two entry
    points into the same backend, and it is why every generator in a dylib module
    takes the C++20 path even when the A3 stack-switch lowering would have
    claimed it.

## Which modules are actually exposed

The production stdlib is CLEAN, and that is worth measuring rather than
assuming: parsing all 249 modules of `build_stdlib()`'s own module list with the
project's own parser and asking for `FunctionDef`s whose `is_generator` (or
`is_async`) is set finds

    modules parsed: 249   parse failures: 0
    modules with a REAL generator/async def: 0

Zero. A `'yield' in source` scan says 16, and every one of those 16 is a
docstring — `std/builtin/range.mojo`'s is "a zero step **yields** an empty
range" — so a text scan is worse than useless here: it names the two modules
whose absence matters most (`range`, `list`) and is wrong about all of them.

So the exposure is exactly the module lists that carry PYTHON-family modules:

  * the compiler's own closure, which is how this was found — `mojoc`,
    `stage2/mojo` and the `mojo dylib` the self-host build links them against
    are all built from `cas.selfhost_inputs()`-shaped lists that include
    `build_stdlib_dylib.py` itself;
  * `mojo dylib` over a project whose own `.py` modules contain a generator the
    A3 pass declines. Nothing reports it: the dylib links (it is `undefined=True`
    for a production dylib, and `mojo dylib` takes the same path), the module's
    generators are simply missing from it, and every client falls back to source.

Within the self-host closure the population is small and now measured to be
enforceable: 61 modules, 3 generator/async functions before lowering, 0 after —
which is what `test_selfhost.py::closure_coroutines_are_lowerable` asserts.

## Next step

Two candidate fixes, and the choice is a judgement call that belongs to whoever
can gate it:

1. **Make the dylib path run the same pre-passes and honour `generated_cpp`.**
   Route `compile_module_to_c` through `gimple_codegen._run_pipeline` (so it
   stops being a second front door into `gen_module`), and give
   `_compile_one_object` a companion: compile `generated_cpp` with `cxx` into a
   second object, return both, and let `build()` append it to `objs`. The
   runtime units already do exactly this — `_RUNTIME_UNITS` entries with
   `_lang == 'c++'` are compiled by `find_gxx()` and folded into the same link,
   and the final link driver is already `cxx`. The work is in the plumbing:
   `_compile_module_job`'s return tuple, the CAS key for the second object, the
   symbol-collision dedup over two objects per module, and the reflection
   export cross-check (`_defined_symbols` is called per `ofile`).
2. **Refuse instead.** Have `compile_module_to_c` raise when
   `gen.generated_cpp` is non-empty, so `build()`'s existing per-module error
   path prints `skip <module>: ...` and the client falls back to source — the
   same honest degradation the dylib already uses for a module it cannot
   compile. One line, and it converts a silent hole into a visible one. It does
   NOT fix the affected module lists above; it only stops them being quietly
   broken, and it costs a `skip` line per generator-bearing module, which is the
   count CLAUDE.md tells you to watch.

Either way, `test_selfhost.py::closure_coroutines_are_lowerable` should stay:
it is the invariant for the SELF-HOST closure specifically, and it is cheap.
