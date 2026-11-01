# Callable return type for check_all: research for Sonnet 5.5

Owner direction (2026-10-30): maximal compatibility with Python; eventually fix all bugs; the compiled code must coexist with the C API (fopen, write and so on), with the usual limits. Research and ANSWER this, do not start a fix.

## The question
The callable-return-type fix for `check_all` (Tools/c-analyzer) can take one of three routes:
- A-rev: a whole-program reverse-import index, which needs a module CAS key change and a full gate.
- A-local: local only. It fixes nothing for this file.
- C: keep the refusal and close the doc as a known limitation (the worker recommended C unless A-rev is acceptable).

## What to answer
1. Which route gives the most Python compatibility at the least risk? Name the exact CAS key change for A-rev and what it invalidates.
2. Is the refusal (C) compatible with the goal of fixing all bugs, or does it close a path for good?
3. Give the gate cost of each route, measured or estimated.

Source doc: bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md

## Status (2026-10-31) — the answer, with the measurements it rests on; no code landed

Measured this round (read, not run): `check_all` is `for check in checks or (): for data, failure in
check(analysis): ...` (`c_analyzer/__init__.py:92`). Its only callers are in OTHER modules
(`c_analyzer/__main__.py:331` passes `checks` built there), and `checks` is a LIST of different functions,
not one function. Two consequences the earlier route table did not state: (a) evidence must come from the
importers, and (b) "all call sites resolve to one function" is the wrong gate, because `checks` holds
several; the right gate is that every callable that can reach the parameter yields an element of the SAME
C type (here, a `(data, failure)` pair), which is what the loop body needs.

### 1. Which route, and the exact key change

**Recommended: a fourth route D, specialise the callee in the importer's own compile; A-rev as the fallback.**

- *D (specialise per evidence set).* When module M calls `f(..., checks=<arg>)` and `f`'s parameter is
  iterated/called for a result type, the importer's compile (which already folds `f`'s module content through
  `dep_fingerprint`, `cas.module_key`, cas.py:465) instantiates `f` with the callable parameter's element
  type fixed by the arguments visible at the call site: a name bound to a top-level `def`, a list/tuple
  literal of such names, or a local bound once to one. Anything else (a parameter passed through, a default,
  a computed list) keeps today's named refusal. The clone is keyed like every other instantiation
  (`cas.instantiation_key(template_id, type_args, comptime_args, ...)`, cas.py:524) with the evidence set as
  `type_args`. **No reverse index and no key-schema change are needed**, because the dependency runs
  importer -> callee, the direction the keys already follow. `monomorphize.py` is the existing home.
- *A-rev.* Needs the callee's object to depend on its importers. The change: `cas.module_key` gains a
  `rev_fingerprint` argument appended exactly like `dep_fingerprint` (only when non-empty, so every module
  without a callable-parameter function keeps its key and the stdlib is not cold-rebuilt by the schema);
  it hashes the content of every module in the compile's closure that calls such a function. It invalidates
  only objects of modules that contain a callable-parameter function, and only when one of THEIR importers
  changes. It cannot be used for the stdlib dylib (`build_stdlib_dylib.py`): a dylib object is built before
  any importer exists, so for that path the evidence pass must stay off and the refusal stays. That
  asymmetry is the argument for D.
- *A-local* fixes nothing for this file (callers are in another module), as the doc says.

### 2. Is C (keep the refusal) compatible with fixing everything?

Yes as an interim, no as an end state. The refusal is loud and named (`callable-valued local/parameter
'check(...)'`, pinned by `test_regress_check_all`), so it closes no path: nothing silent depends on it. But
five files wait on this one shape, and the owner's direction (maximal Python compatibility) rules out
leaving it as the destination. Treat C as the fallback inside D for every argument shape D cannot see.

### 3. Gate cost

Any edit under `mojo/backend_gimple/*` changes `compiler_fingerprint()`, so BOTH routes cost one cold CAS
rebuild: measured elsewhere in this queue, ~8 min for a quiet cold dylib/bootstrap run (484-517 s) and the
~32 min bootstrap chain. Beyond that: D adds one compile per distinct evidence set per importer (the
instantiation cache absorbs repeats); A-rev adds a closure scan per compile plus re-compiles of the callee
module for each importer change. Both owe `make gate` and the two judgement checks (stdlib-dylib `skip`
count must not rise; `compile_stdlib.py` `U` must not rise). Because D adds a new emission path, also
`cmp` the C of a large succeeding closure before/after: it must be byte-identical for every program with no
callable-parameter function.

### First step (next round, executable without re-investigating)

1. `monomorphize.py`: add `callable_param_evidence(call_node, callee_def)` returning the list of top-level
   `def`s reaching each callable parameter, or None. 2. `cpp_core.py` `for` branch (~7350, the refusal):
   when the callee is a callable parameter and the enclosing function is an instantiation carrying evidence,
   lower the inner loop as an ordinary `for` over the unified return type. 3. Tests in
   `test_gimple_generator_runner.py`: one importer + a two-function list with equal element types compiles
   and matches CPython; two functions with different element types stays refused; a default argument stays
   refused (a default is not call-site evidence).

## Status (2026-11-01) — measured on the C gimple path; one partial implementation reverted

Reproduction without the c-analyzer sources (`for d, e in f(xs)` with `f` a callable PARAMETER, and `for f in fs: for d, e in f(xs)` with `f`
a loop variable over a list of generator functions): the compiled program prints `mojo_unsupported_iter: 'for' loop over unsupported iterable
type int64_t` on stderr, exits 0, and the loop body runs zero times (CPython prints every yielded pair).

Tried and NOT landed: in `emit_loops._gen_for_iter`, a call through a callable variable/parameter dispatched by `mojo_dyn_call`
(`_lower_fnptr_spread_call`) and drained with `mojo_iter_word` makes the loop run the right number of times with the right first slot, but the
second slot of each yielded tuple is wrong when it is a `None` or a string (prints `0` / a pointer), because the generators involved
(`yield x, None` / `yield x, "big"`) take the C++-coroutine path and their tuples carry no per-slot kinds to the dynamic reader. A loop that
runs with silently wrong values is worse than one that prints the diagnostic, so it was reverted. The missing piece is the tuple-kinds
contract between the C++ generator's yield and `mojo_iter_gen_handle`/`_gen_drain` (its `vkind` 4 'l' case): it must record the per-slot kinds on
each yielded tuple (`mojo_list_set_kinds`), and the dynamic loop must read the targets with `mojo_list_get_boxed`. Do that first; the
evidence/specialisation design above is then only needed for the static typing of the loop targets.

## Status (2026-11-01, later) — the non-generator half LANDED; the generator-that-re-yields half is still loud

Landed: `for d, e in f(xs):` where `f` is a callable PARAMETER or a loop variable over a list of generator functions, in an ordinary
function, now matches CPython (`gimple_for_over_a_call_through_a_function_value`): `emit_loops._gen_for_iter` dispatches the call through
`mojo_dyn_call` (a generator is bound by its registered name), drains it with `mojo_iter_word`, and reads the tuple targets BOXED, so a
`None`, a string or a float beside an int keeps its kind. The C++ generator side records those kinds: `_cpp_yield_tuple` builds a tuple that
has a `None` slot with the kind-recording appends (`mojo_list_append_word` / `_double_kinded` / the new `mojo_list_append_str_kinded`, which
tags a string literal that lives in the coroutine unit and is not in the runtime's registered pool). A tuple without a `None` keeps its plain
appends (a double beside an unknown int64_t read back as raw bits when it did not, caught by `cpp_coroutine_mixed_kind_list_param_tuple_yield`).

NOT done: the shape `check_all` really has, a GENERATOR whose body loops over `check(analysis)` and re-yields the pair. The stack-switch
body re-yields `d, e` as plain int words (no kinds), so the dynamic loop is disabled inside a coroutine body (`gen._cur_func_is_coro`) and that
shape keeps its `mojo_unsupported_iter` diagnostic rather than printing wrong values. Next: make the A3 yield of a tuple whose slots are dynamic
words record their kinds (the same `mojo_list_append_word` discipline), then drop the `_cur_func_is_coro` guard.
