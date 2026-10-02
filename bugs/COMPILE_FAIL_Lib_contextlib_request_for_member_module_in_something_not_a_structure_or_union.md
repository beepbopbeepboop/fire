# COMPILE_FAIL: Lib/contextlib.py — blocked on the async/coroutine codegen (title STALE)

## Status (2026-09-30 — rewritten; not an import-qualifier bug, not attempted)

Its current blocker is NOT an import/qualifier problem and not the one
in the title: it is the async/coroutine codegen. The refusal is raised from
`mojo/backend_gimple/module_gen.py`'s async-function eligibility gate
("cannot compile module: function(s) ... (async function(s), declared
`async def`)"), and the per-function reasons are emitted verbatim by
`mojo/backend_gimple/cpp_async.py` — `__aenter__`: "every `return` must
carry a scalar value" (line ~1878) and `__aexit__`: "*args/**kwargs
parameters not supported for compiled async functions" (line ~1616). Both
are still exactly those two messages in the current tree.

That is: non-scalar `__aenter__`-return boxing/type-erasure plus
variadic `__exit_wrapper` parameters in the C++20 coroutine frame — a
genuinely large feature, and not in the decorators/import-qualifiers area
this doc was filed under. Filed here originally for a `request for member
'__module__'` GCC error that stopped happening long before 2026-08-06 (the
title and the original note are STALE, as the 2026-08-06 entry below
already said); the accumulated "re-verified unchanged" entries after that
are what a `bugs/` entry is supposed to stop being, so they are gone.

**Next step** (unchanged in substance, now stated once): extend
`cpp_async.py`'s coroutine codegen to box non-scalar `__aenter__` returns
and to carry `*args`/`**kwargs` in the coroutine frame. Nothing about
imports, decorators or symbol qualification is involved.
