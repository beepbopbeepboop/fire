# CODEGEN_a_bare_or_explicit_yield_of_none: a None yield value prints 0

A generator that yields `None` (bare `yield` or explicit `yield None`) prints
`0` on the compiled path where CPython prints `None`. Every other value type
the generator value-slot lattice supports (int / bool / float / str) matches
CPython on BOTH the local and global generator paths. None is the only
mismatching type. Owner-level ABI feature; measured and pinned, NOT shipped.

## Status (2026-10-31, partial fix landed on work/bug-codegen-a-bare-or-explicit-yield-of-3467)

**Landed (real behaviour change, stackswitch default path, for-loop consumers):**
a generator whose yields include a bare `yield` / `yield None` is now a TAGGED
word (`'w'`) when `_tagged_consumers_ok` holds, and each None yield is boxed by
the new `mojo_box_none()` (runtime/fire_runtime.c, a shared kind-`'n'` box that
`mojo_repr_boxed` already rendered as `None`). Pins: `run_none_yield_tests` in
`test_gimple_generator_runner.py` (3 cases, CPython oracle; 0/3 before the fix,
3/3 after; full file 354/0). The mechanism is `_is_none_yield` +
`has_none` in `_generator_value_kind` (mojo/middle/coro.py), `_rewrite_expr`'s
`kind == 'w'` arm. `_yield_kind` is unchanged (it has ~15 callers).

**Still open (the next steps, in order):**
1. `next(g())`, `list(g())`, comprehensions, `sum`, and other non-`for`
   consumers still print `0`: the tagged word is for-loop-only by design
   (`_tagged_consumers_ok`), so a None-yielding generator used that way keeps
   its int64_t slot. Needs a None-aware `next()` reader (`__mgco_<base>_value`
   consumer), not the tagged path.
2. An explicit `yield None` beside a str or float yield is still REFUSED by the
   C++ fallback typer (`mojo/backend_gimple/cpp_async.py`, `value_ctype is None`
   raised at ~1177): the cpp typer reads `None` as an unresolved hole. The module
   then falls back to the interpreter, which is correct output but not compiled.
   Next step: `cpp_core.py` (~5366 bare yield emits `co_yield (int64_t)0;`, and
   the `/*Y:…*/` marker at ~5376 has no `none` tag) plus `_cpp_tag_yield_sites`
   (cpp_async.py:322) need a `none` marker boxed by `mojo_box_none()`.
3. The `MOJO_CORO=cpp` escape hatch (`cpp_core.py` bare yield) still prints `0`
   in its own output.
4. `_list_word_push` (runtime) has no None arm, so a None box appended to a list
   becomes an int; unreached by the for-loop path, but a real gap for list use.

**Gate status:** not run here (light-worker rules). The integrator should run
`gimplegenerators` and `compile_stdlib.py`: this change moves stdlib generators
with a bare `yield` consumed by a `for` loop from the int64_t slot to the tagged
word, so `stdlib-dylib`'s `skip <module>:` count and `stdlib-syntax`'s
`U` count must be compared before and after.

## Status (2026-10-28, master 8c19a643f — value matrix measured 2026-10-26 on 1d2bdfe0; the mechanism was re-located on 8c19a643f and is intact)

### Value-type matrix (fresh-store build each; binary output vs CPython on the same text)

| shape | local | global | CPython |
|---|---|---|---|
| bool (`yield True`) | MATCH [True True] | MATCH [True True] | True True |
| float (`yield 1.5`) | MATCH [1.5 1.5] | MATCH [1.5 1.5] | 1.5 1.5 |
| str (`yield "hi"`) | MATCH [hi hi] | MATCH [hi hi] | hi hi |
| int (`yield 1`) | — | MATCH [1] | 1 |
| None bare (`yield`) | MISMATCH [0] | MISMATCH [0] | None None |
| None explicit (`yield None`) | — | MISMATCH [0] | None |

Artifacts: `T/opencode/fsdec/poison1/vabi/{bool,float,str}_{local,global}.py`,
`poison1/vabi/none_explicit_global.py`, `T/opencode/fsdec/A1_inspect.c`
(regenerated A1 C with the failing lowering visible at `_t1 = (int64_t)0;
__mojo_coro_yield_i (__c, _t1);`). The fuller matrix is 6 types x local/global.

### Pin (re-located on 8c19a643f; the owner's integ batch shifted lines, grep to re-find)

`mojo/middle/coro.py` — the default stackswitch generator backend
(COROUTINE.html §5.5 cutover):

1. The value-slot lattice `_KIND_CTYPE` = `{'i': 'int64_t', 'b': '_Bool',
   'p': 'char *', 'd': 'double', 'tuple': 'MojoList *'}` has **no None/void
   kind** — a None value cannot be represented in the word at all.
2. `_rewrite_async_expr` (coro.py:1550 on 8c19a643f): a None yield value
   becomes `N.IntLiteral(value=0)` — the measured A1 C shows the bare yield
   lower to `__mojo_coro_yield_i(__c, 0)`, **indistinguishable on the wire
   from an explicit `yield 0`**.
3. Consumer: `next()` reads `__mgco_<base>_value (MojoGenerator *) ->
   int64_t`; print renders the raw 0.

### What a fix requires

The generator **value ABI itself**: a None channel needs a tagged/void word
(or a distinct `'n'` kind plus a consumer-side None marker), touching every
generator value reader (`next()`, send loops, tuple slots). This is a
trust-model/ABI change, not a one-site fix.

The owner's six-case module-global-generator suite
(`test_gimple_generator_runner.py`, `run_module_global_generator_tests`) only
tests valued yields — a fix must add a None-yield case there, and the value
matrix above is the oracle: the fix must print `None` in the binary while
every valued-yield shape keeps MATCH.

### Guardrails

No false greens: a fix that makes `yield` print `None` by special-casing
`print` (instead of carrying None through the ABI) is a regression — the
valued-yield shapes must still round-trip their REAL values, and
`gimplegenerators` must stay green. Status: open, owner-level.
