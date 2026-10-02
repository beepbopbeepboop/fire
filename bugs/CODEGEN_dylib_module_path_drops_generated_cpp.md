# The dylib module compile throws away `generated_cpp`, so a generator in any dylib module silently loses its definitions

## Status (2026-10-02, `work/bugs4-2`) — candidate 2 (REFUSE) is LANDED and pinned; candidate 1 (the real fix) is not

`build_stdlib_dylib.compile_module_to_c` now raises when
`gen.generated_cpp` is non-empty, so `build()`'s existing per-module error
path prints `skip <module>: ...` and the client falls back to source. The
exception is a named class (`_DylibGeneratedCppError`) rather than a bare
`RuntimeError`, so a caller that DOES know how to link a companion object can
tell it apart from a genuine compile failure — candidate 1 is exactly that
caller, and it should not have to match on a message.

Pinned by `test_selfhost.py::dylib_module_path_refuses_a_generated_cpp`, which
is deliberately the OTHER half of `closure_coroutines_are_lowerable`: that check
asserts the exposure is ABSENT for the two module lists that ship, and an
assertion that the exposure is absent is not a refusal when it is not. It
compiles a decorated generator (the shape the A3 stack-switch pass refuses, so
the C++20 emitter takes it and `generated_cpp` is the only place the
definitions exist) and requires the refusal, and then compiles a
generator-FREE module and requires that it still compiles — the second half is
what keeps the refusal from costing anything on the module lists that ship.

Cost on this tree: **zero `skip` lines**, measured two ways.
`closure_coroutines_are_lowerable` still reports 61 modules / 0 unlowered, and
the production stdlib is 249 modules / 0 real generator-or-async defs (the
entry above's own census, re-confirmed by the refusal not firing for a plain
generator module either — which is the sharper statement, because a plain
generator is exactly what the C++20 emitter accepts). So the sequencing advice
this doc gives stands, and candidate 1 now has a measurement to not increase:
the skip count the refusal adds.

What candidate 1 still needs is unchanged and is the doc's own open decision:
route `compile_module_to_c` through `gimple_codegen._run_pipeline` (so it stops
being a second front door into `gen_module`), and give `_compile_one_object` a
companion that compiles `generated_cpp` into a second object. The new
`_DylibGeneratedCppError` is the seam to do that behind — a caller that wants
the object can catch it, and a caller that does not is already correct.

## Earlier status


**Open. Root cause of the 2026-10-01 `mojoc` / `selfhost` / `bootstrap-stage2-cc`
red, which is fixed at the call site, not here.** One `@contextlib.contextmanager`
in `build_stdlib_dylib.py` was enough to make the whole self-host build fail to
link; it is now a class (commit `ccd83a2b`), and
`test_selfhost.py::closure_coroutines_are_lowerable` keeps the shape out. What
is left is the hole that let it through, which is much wider than one function
and is not fixed.

**The hole let a SECOND instance through, in the same batch, and that one is
also fixed at the call site (2026-10-01).** 73799ca2's consolidation of three
copies of a local-type walk in `mojo/middle/infra_infer.py` turned the recursive
`walk` into a generator — `_each_binding` is a `yield from` tree — and
`mojo/middle/infra_infer.py` is in the self-host closure. The static half named
it exactly ("the stack-switch lowering left _each_binding, walk") and the built
compiler then segfaulted on its first two-line program. It is an accumulator
returning a list now, the same conversion (and the same reasoning) as
`mojo/middle/coro.py`'s `_walk`.

The pattern worth recording is that **the static half is the only cheap detector
for this class, and it was written before either instance arrived.** Both
arrived anyway, in the same batch, from branches that had no reason to think
about the self-host closure at all — one was a `@contextlib.contextmanager` and
the other a three-copies-into-one refactor. Neither is a generator anyone would
spot by reading the diff. That is the argument for candidate fix 2 below (refuse
rather than silently drop) over continuing to rely on one static check per
landing: the check caught both, but only because someone ran it.

Not fixed here on purpose: the fix changes what every dylib module's compiled C
looks like (or adds a C++ object per generator-bearing module to the dylib link
line), which is a `make gate` change, and this was landed by a worker that is not
allowed to run one.

## Status addendum (2026-10-01, `work/bugs3-codegen-2-r2` — the choice is still a choice, and the measurements that settle it are still missing)

Nothing here was fixed, and the reason is unchanged and concrete: both
candidate fixes change what every dylib module's compiled C looks like (or add
a C++ object per generator-bearing module to the dylib link line), and
verifying either needs `build_stdlib_dylib.py` end to end plus
`compile_stdlib.py`'s `U` count — a `make gate` this branch is not allowed to
run. Re-deciding the choice from the source would be worse than leaving it to
whoever can gate it, so this addendum records only what can be established
cheaply, and one thing that is now known that the entry above does not say.

**What is now known: the exposure inside this tree is ZERO, measured.** The
entry above measured the *production stdlib* is clean (249 modules, 0 real
generators). The self-host closure was measured too
(`test_selfhost.py::closure_coroutines_are_lowerable`: 61 modules, 3
generator/async functions before lowering, 0 after). So on THIS tree no dylib
module carries a `generated_cpp` at all, and neither candidate fix changes a
single byte of generated C for any module in either module list. That is worth
saying plainly because it changes the risk calculus: candidate 2 (refuse)
costs **zero** `skip` lines today, not "a skip per generator-bearing module",
and candidate 1's plumbing is exercised by nothing here either.

**So the cheap sequencing advice is the reverse of what the entry implies**:
land candidate 2 first (a one-line refusal, invisible on this tree, and it
converts the hole into a visible one for the module lists that DO have
generators — a project's own `.py` under `mojo dylib`, which is where the
silent wrong behaviour actually bites), then candidate 1 as the real fix, with
candidate 2 as the invariant that must keep the two consistent. Doing them in
that order means the real fix is never the first thing to touch a link line,
and the refusal's own skip count becomes the measurement candidate 1 has to not
increase — which is the CLAUDE.md `stdlib-dylib` before/after comparison, used
for the first time on a count that starts at zero.

**The measurement candidate 1 needs and nobody has taken** is what the doc
should say is next: the two _compile_one_object / link-mode paths differ, and
the difference is not cosmetic — `fire.py build_executable` already inlines
each imported sibling's `generated_cpp` through
`_compile_imported_module` → `_compile_link_inline_cpp_unit`
(`mojo/backend_gimple/emit_resolve.py:912`), while `compile_module_to_c` does
not even run `gimple_codegen._run_pipeline`'s pre-passes. **Before writing any
plumbing, measure how many module lists actually reach
`compile_module_to_c` with a non-empty `generated_cpp`** — over
`cas.selfhost_inputs()`-shaped lists, over `mojo dylib` on a project whose own
`.py` has a generator the A3 pass declines, and over the production stdlib
(known: zero). If the answer is "only user projects", candidate 2 alone is a
complete and honest fix for this tree and the plumbing is a separate,
better-informed change.

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
