# HARD BUG (performance): `_walk_ast` re-scan blowup for large transitive-import graphs

## Status

Unfixed. Confirmed pre-existing (present at commit d3c05b4, before any of
this session's fixes) -- not a regression introduced this session. Real
architectural scaling issue in the nested whole-program compilation flow,
not a quick fix.

## Symptom

`python3 mojo.py build <file>.py` (`do_imports=True`) takes minutes (or
times out entirely against the 60-90s harness timeout) for any file whose
transitive import graph is moderately large, even though the file itself
is small and the actual GIMPLE/C++ codegen for it is fast in isolation.

Confirmed via `Lib/contextlib.py` (imports `abc`, `collections`,
`functools`, `os`, `sys`, `types`, `warnings`, ...): a direct, isolated
`gimple_codegen.compile_to_gimple(src, do_imports=True)` call on just
`contextlib.py`'s own source completes in **0.17s** (it raises a `RuntimeError`
early — contextlib.py has `async def`s this codegen can't compile — which
is caught cheaply). But the real `mojo.py build` CLI path (which, after
catching that RuntimeError, retries via `compile_to_gimple_with_cpp` to
attempt the C++ coroutine path for the async functions) still hadn't
finished after **20 seconds of profiled CPU time** on the SAME file,
confirmed via `cProfile`:

```
86320467 function calls (80837078 primitive calls) in 19.968 seconds
[after a 20s SIGALRM interrupt, build had not completed]

ncalls    tottime  cumtime  filename:lineno(function)
1         0.000    19.966   gimple_codegen.py:31258(compile_to_gimple_with_cpp)
36/1      0.843    19.906   gimple_codegen.py:24713(gen_module)
64/3      0.006    19.881   gimple_codegen.py:4127(_compile_imported_module)
4473166/6376  3.816   8.858  gimple_codegen.py:2037(_walk_ast)
35        0.527     8.014   gimple_codegen.py:26255(_scan_body_for_local_field_access)
35620760  2.786     2.786   {built-in method builtins.isinstance}
4561633   1.415     2.198   dataclasses.py:1476(is_dataclass)
```

`_walk_ast` (a recursive, module-level AST walker) is called **4.47
million times** for just 36 nested `gen_module` invocations (one per
transitively-imported module) -- roughly 124,000 calls per module, far
more than a single linear pass over that module's own statements would
require.

## Root cause (partial diagnosis)

`gen_module` calls `_scan_body_for_local_field_access` (and similar
scanners like `_collect_self_assigns`/`_collect_self_reads`, both used for
struct field-type inference) over `stmts + imported_stmts`. Each nested
`_compile_imported_module` call (triggered while compiling one module's
own imports) appears to invoke `gen_module` again for the next module
in the transitive chain -- and each of THOSE invocations' own
`_scan_body_for_local_field_access` pass walks its own accumulated
`imported_stmts`, which by construction includes every module already
pulled in by outer/sibling calls. For a transitive graph of N modules
where each nested compile re-walks the (growing) cumulative import list
instead of only its own module's fresh statements, total AST-walk work
scales worse than linearly in N -- consistent with the 4.47M call count
observed for a 36-module graph.

This diagnosis is **not confirmed by reading the caching/memoization
logic in `_compile_imported_module` line by line** -- it's inferred from
the profile shape (many more `_walk_ast` calls than a single linear scan
of the total transitive source would need) and is the most likely
explanation, not a verified root cause.

## Why this wasn't caught before

`test_gimple.py`/`test_module_cache.py`/`compile_stdlib.py` all compile
individual `.mojo` files or small, curated fixtures -- none of them
exercise `do_imports=True` against a REAL, large, deeply-nested-import
Python stdlib file the way the bugs/*.md harness (`py314_harness.py`,
90s default subprocess timeout) does. `make check-selfhost` compiles
`mojo.py` itself, which is a single large file with a comparatively
shallow, mostly-already-cached import graph, not a fresh cold-cache deep
chain like `contextlib.py`'s.

## Affected files (from the bugs/*.md corpus, 60s harness timeout)

At least 16 files hit this (re-triaged 2026-08-06): `Apple/testbed/
__main__.py`, `Doc/conf.py`, `Doc/includes/dbpickle.py`, `Doc/includes/
email-alternative.py`, `Doc/includes/mp_newtype.py`, `Doc/includes/
ndiff.py`, `Doc/includes/newtypes/setup.py`, `Doc/tools/check-epub.py`,
`Doc/tools/check-html-ids.py`, `Doc/tools/check-warnings.py`, `Doc/tools/
extensions/availability.py`, `Doc/tools/extensions/c_annotations.py`,
`Lib/contextlib.py`, `Lib/poplib.py`, `Lib/runpy.py`, `Lib/socket.py`.
Several of these (the small `Doc/includes/*.py` one-off examples) are
almost certainly NOT large or complex in themselves -- their slowness is
consistent with pulling in one or two large stdlib modules (e.g. `email`,
`multiprocessing`) transitively, which is exactly the "deep import graph"
shape this bug is about.

## What a real fix needs

1. Confirm the exact re-scan mechanism (read `_compile_imported_module`
   and `gen_module`'s Phase-1/Phase-2 structure carefully to see whether
   `imported_stmts` genuinely accumulates and gets re-walked per nested
   call, or whether the blowup has a different, still-undiagnosed cause).
2. Memoize per-module scan results (field types, generator/async
   detection, etc.) keyed by module identity, so a module already fully
   processed once in this whole-program compile is never re-walked by a
   sibling/outer module's own scan pass.
3. Re-profile against `contextlib.py` and confirm `_walk_ast` call count
   drops to roughly linear in total transitive source size.

Not attempted here -- this is a structural change to the nested-module-
compilation flow, with real risk of behavior changes elsewhere (module
processing ORDER currently matters for things like same-file overload
resolution and cross-module symbol qualification), not a targeted fix.
