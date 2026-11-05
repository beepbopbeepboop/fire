# CODEGEN_a_bare_or_explicit_yield_of_none: a None yield value prints 0

A generator that yields `None` (bare `yield` or explicit `yield None`) prints
`0` on the compiled path where CPython prints `None`. Every other value type
the generator value-slot lattice supports (int / bool / float / str) matches
CPython on BOTH the local and global generator paths. None is the only
mismatching type. Owner-level ABI feature; measured and pinned, NOT shipped.

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
