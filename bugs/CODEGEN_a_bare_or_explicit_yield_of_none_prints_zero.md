# CODEGEN_a_bare_or_explicit_yield_of_none: a None yield value prints 0

A generator that yields `None` (bare `yield` or explicit `yield None`) prints
`0` on the compiled path where CPython prints `None`. Every other value type
the generator value-slot lattice supports (int / bool / float / str) matches
CPython on BOTH the local and global generator paths. None is the only
mismatching type. Owner-level ABI feature; measured and pinned, NOT shipped.

## Status (2026-11-01, seventh round, work/bug-codegen-a-bare-or-explicit-yield-of: planning guide for the bind-site kind loss, no code changed)

**Output of this round: a planning guide (not a fix).** The open item is the
bind-site kind loss (since fixed in `b09622930`, which keeps the box at the
bind):
`x = next(g)` on a tagged generator unwrapped the box at the bind, so `print(x)`
printed a bool as `1` on the default path and an address on the cpp path.
Investigated, not landed: the change crosses per-function state and several
consumers, and it reverses a deliberate design, so it needs its own round with
the full pin set below.

**Current state (carried from the sixth round's measurements; not re-run):**
the repro in the bind-site doc prints `'1\nb\n'` default (CPython `'True\nb\n'`)
and `'1\n<address>\n'` on `MOJO_CORO=cpp`.

**Where the unwrap is (measured by reading, master 7ceb5092e):**
- `mojo/backend_gimple/emit_stmts.py` ~1321-1334: a `vtype == 'int64_t'` value
  whose temp is in `gen._boxed_vals` is bound through `mojo_box_word` into a
  fresh temp, and the LOCAL is NOT added to `_boxed_vals`. The comment there
  records why: a local that kept the box broke `v is None` (a non-NULL heap
  box), which is the `_mojo_classattr_init` / `_class_field_decl` regression.
  Any fix must keep that case correct.
- Tagged-word temps are added to the SAME `_boxed_vals` set as list-element
  boxes: `mojo/backend_gimple/emit_calls.py` ~369 (`_lower_generator_next`) and
  ~2919 (two-argument `next(it, default)`), and `emit_loops.py` ~2590/3930 for
  for-targets. So the bind site cannot tell a tagged word from a list box today.
- Per-function scope: `_boxed_vals` is saved/restored in
  `mojo/backend_gimple/emit_infra.py` (`save_func_state` ~969/1052, restore
  ~1077/1164). A new set must follow the same pattern (or the code must reuse
  `_boxed_vals` with a tag), not leak across functions.
- Cpp side: `_cpp_tagged_word_names` (`cpp_core.py` ~1941-1960) already tracks
  tagged locals inside coroutine bodies. The failing cpp repro is `_gimple_main`
  (a NON-coroutine binder), so the GIMPLE bind fix covers it; no cpp change is
  needed for the bind itself.

**Consumers of a `_boxed_vals` local (what the fix must get right):**
`emit_exprs.py` ~3930-3946 (arithmetic `mojo_box_word` on operands, already
correct for a boxed name), ~4699-4704 (compare: the `is None` path; this is the
consumer the classattr comment is about), `emit_infra.py` ~2556/2733 (call
arguments), ~4789 (`str()` / print via `mojo_repr_boxed`, already correct),
~5030 (`mojo_box_int` for numeric use), ~7071-7079 (format/`str` of an int
argument). Each must give the box's VALUE for every kind; the audit is the work.

**Decision (recommended): tag, do not overload.**
1. Add `gen._tagged_word_vals` (temps produced by the two tagged-`next`
   sites above), save/restore it in `emit_infra.py` next to `_boxed_vals`.
2. At the bind (`emit_stmts.py` ~1327): if `v in gen._tagged_word_vals`, do NOT
   `mojo_box_word`; keep the box, add the LOCAL's cname to `_boxed_vals` and to a
   new `gen._tagged_word_locals`. Leave the list-element path unchanged.
3. Rebinding is the hazard: `_boxed_vals` membership is static, so a name that
   is later rebound to a plain int would still be treated as a box. Rule: mark
   the local ONLY when every assignment to that name in the function is a
   tagged-word bind (scan the function body's `Assign` targets once, at the
   bind site or in a pre-pass). Any other assignment makes the name untagged,
   and the old `mojo_box_word` path stays.

**Tests (write first, must FAIL before the change, CPython oracle), in
`test_gimple_generator_runner.py` next to `run_tagged_word_cpp_tests`:**
- the two-line repro (`x = next(g); print(x)` twice), default and
  `coro.pinned('cpp')`: expect `True` / `b`.
- `x = next(g); x + 1` on an int-first mixed generator (arithmetic still works).
- `x = next(g); print(x is None)` on a None-yield tagged generator (the
  `is None` consumer the classattr regression is about).
- rebinding: `x = next(g); x = 5; print(x)` must print `5` (guards the
  every-assignment rule).
Run only that file, under `python3 tools/memslot.py --gb 8 --label x --`.

**Gate note for the integrator:** this change widens which generator-bound
names keep the box, so `stdlib-dylib`'s `skip <module>:` count and
`stdlib-syntax`'s `U` count must be compared before and after, and the
classattr emission (`_mojo_classattr_init`) checked for byte-identical C on a
large case (the behaviour-preserving standard applies to every non-tagged path).

**Still open in this doc (unchanged):** the dead `co_yield (int64_t)0` line
(item 3), the module-global `next()` refusal (its own doc), and the remaining
non-`print` consumers of a tagged value on the cpp path.

## Status (2026-11-01, sixth round, work/bug-codegen-a-bare-or-explicit-yield-of: escape-hatch word print, partial)

**Landed (real behaviour change on the `MOJO_CORO=cpp` path, measured against
CPython):** a TAGGED word (a generator whose yields mix kinds) is now printed
as the value it boxes, not as the box's address. Two layers:

- *Str yields were not boxed.* `_cpp_tag_yield_sites` (cpp_async.py) stored a
  `char *` yield as a raw pointer, which the runtime reads as a string only
  when it is registered (a C++ literal is not). It now boxes it with a new
  `mojo_box_from_str` (fire_runtime.c/.h): a kind-`'p'` box, the same
  convention as `mojo_box_from_double` / `mojo_box_from_bool`.
- *Consumers did not know the slot was tagged.* The generator api dict now
  carries `'tagged'` (set at the tagging site as `gen._cpp_last_tagged_yield`,
  registered by `module_gen._register_free_generator` and the nested-generator
  api). The C++ emitter (cpp_core.py) marks the locals bound from a tagged
  generator (`_cpp_tagged_word_names`: a direct-call `for`, a generator-handle
  `for`, `x = next(g)`), and the single-argument `print` renders a tagged word
  through `mojo_repr_boxed`. `_cpp_tagged_next_api` / `_cpp_is_tagged_word_expr`
  / `_cpp_mark_tagged_word` are the helpers.

Pins: `run_tagged_word_cpp_tests` in `test_gimple_generator_runner.py`, six
cases, all under `coro.pinned('cpp')`, CPython oracle. Measured on a HEAD
snapshot (pre-fix): 5 of 6 FAIL (the int/str for-loop and next() print an
address; the two generator-body shapes are refused as "print() argument must
be a scalar", falling back to the interpreter). `tagged_int_float_for_loop_cpp`
already passed before the fix and is a regression guard, not a fail-before pin.
After: 6/6. `test_gimple_generator_runner.py` 368/0; `test_gimple_async_runner.py` 39/0.

**Scope of the consumer change, stated plainly:** the C++ emitter renders a
tagged word only in the three consumer sites above and only for a single-argument
`print`. A tagged value used any other way (arithmetic, `str()`, an f-string,
a multi-argument `print`, `list.append`) is not covered by this round.

**Found and FIXED (separate defect, default path too), in `b09622930`:** a
tagged value bound to a name in the GIMPLE consumer was unwrapped by
`mojo_box_word` at the bind, so `x = next(g); print(x)` printed a bool as `1`
on the default path, and an unregistered str on the cpp path printed an
address. The bind now keeps the box for a tagged word; pinned by the
`tagged_*_bound_to_name_*` cases (`run_tagged_word_bind_tests`) in
`test_gimple_generator_runner.py`.

**Still open in this doc:** item 1 of the fifth-round plan is now landed for
the three consumer sites and `print`; the remaining consumers and the `x`
local-kind design are the next steps. The
`co_yield (int64_t)0` dead line (item 3) and the module-global `next()` refusal
(item 2, its own doc) are unchanged.

## Status (2026-11-01, fifth round, work/bug-codegen-a-bare-or-explicit-yield-of: measured matrix, pins, planning guide)

**Measured (compiled binary vs CPython, same text; `_build_generator_program`
on the default stack-switch backend, and `coro.pinned('cpp')` for the escape
hatch):**

| shape | default local | default global | cpp |
|---|---|---|---|
| bare `yield` beside int, `for` + `next()` | MATCH | `for` MATCH; `next()` refused (see below) | refused (None) |
| explicit `yield None` beside int | MATCH | `for` MATCH; `next()` refused | refused (None) |
| bare-only generator, `for` + `next()` | MATCH | refused (global `next()`) | refused (None) |
| explicit `None` beside str / float | MATCH | refused (global `next()`) | refused (None) |
| int-only global, `next(it)` | — | refused (global `next()`, NOT None-specific) | — |
| mixed int/str, `next()` | MATCH | — | prints a box ADDRESS (`'1\n4335…\n2\n'`) |
| mixed int/str, `for` | MATCH | — | prints a box ADDRESS |

So on the default path no None shape prints `0`: every None shape that
compiles matches CPython, and the rest are honest refusals. The escape hatch
refuses every None yield (no silent 0), but it still has a non-None defect:
a tagged (mixed-kind) generator's value is printed as a raw int64, in `for`
loops and in `next()`.

**Landed this round (coverage, `test_gimple_generator_runner.py`,
`run_none_yield_tests`):** three pins. `none_yield_bare_in_module_global_generator_for_loop`
(default path, MATCH; the global store/read path had no None test).
`none_yield_bare_refused_on_cpp_path` and
`none_yield_explicit_beside_str_refused_on_cpp_path` (under `coro.pinned('cpp')`,
must refuse with "a None yield (bare `yield` / `yield None`) has no value slot").
These guard against a regression to the silent `co_yield (int64_t)0`. No
production code changed this round; none of the three pins fails before the
round-3 refusal, so they are coverage, not a fix.

**Planning guide for the remaining work (not started):**

1. *C++ word print (escape hatch only, the doc's item 2).* A tagged yield is
   boxed at `_cpp_tag_yield_sites` (`mojo/backend_gimple/cpp_async.py:322`,
   called at ~1138 when `_tagged_yield`). Nothing downstream knows the value is
   a word, so the print lowering (`mojo/backend_gimple/cpp_core.py`, the
   `print` single-arg scalar branch ~5500) emits `%lld` for every `int64_t`.
   Plan: (a) record the tagged generator base in a gen-level set
   (`gen._cpp_tagged_gen_bases`) at the tagging site, and carry `'tagged'` in the
   cross-module record (`_cpp_xmod_generator_refs`, cpp_core.py ~1750/1899).
   The API dict (cpp_async.py ~3600 / ~1803) is built from
   `_gen_cpp_generator_unit`'s return, which does not carry the flag. (b)
   `_cpp_next_on_generator_expr` (cpp_core.py ~1878) and the generator
   `for`-binding (cpp_core.py ~7559) mark a tagged value as a word. (c) the print
   branch emits `mojo_repr_boxed((int64_t)(...))` for a word (the stack-switch
   print already does this; the runtime function exists). Ordering risk: a
   consumer emitted before its generator must see the set, so compute tagged-ness
   from the generator's FunctionDef with the same predicate
   (`coro._generator_value_kind(...)[0] == 'w'`), not from emission order.
   Tests: `test_generator_matches_cpython` under `coro.pinned('cpp')` for the
   mixed int/str `next()` and `for` shapes (CPython oracle); must FAIL before,
   PASS after. Gate note: escape hatch only; a `MOJO_CORO=cpp` compile is never
   on the stdlib default path, so the integrator's `skip`/`U` counts should
   not move from this.

2. *Module-global `next()` refusal* is NOT None-specific. It was its own bug
   (`next()` on a module-level generator read from a function was refused: the
   toplevel store, which seeds the generator api, is emitted after every
   function) and is FIXED by `emit_infra.seed_global_generator_apis`, pinned by
   `run_module_global_generator_tests` in `test_gimple_generator_runner.py`.

3. *Dead C++ bare-yield line* (`cpp_core.py`, `co_yield (int64_t)0`): unreachable
   for a None yield now (the typer refuses first). Delete in a cleanup, with
   the pin above guarding it.

**Why this is still open:** the None symptom (`0`) is gone on the default path,
but the escape hatch's word print (item 1) is a separate, pre-existing defect,
and the bug doc's own item 2 is that work. It is not a None issue, so it stays
here as the planning guide rather than a new doc.

## Status (2026-11-01, fourth round, work/bug-codegen-a-bare-or-explicit-yield-of: `next()` reads the None box)

**Landed (behaviour change, compiled path, measured against CPython):** a
None-yielding generator consumed by `next()` now COMPILES and prints `None`,
instead of being refused (third round) or printing `0` (before it).
- `_tagged_consumers_ok` (`mojo/middle/coro.py`) accepts `next(<handle>)` and
  `next(g())` / `next(g(), default)` as tagged consumers. `_lower_generator_next`
  (`mojo/backend_gimple/emit_calls.py`) already marked the result of a `'w'`
  generator as a boxed word; the two-argument `next(it, default)` form did not,
  and read its result as a raw int64_t (printed an address for `next(it, 7)`
  after a None yield). Both forms now mark the result boxed.
- The `default` of a tagged `next(it, default)` is lowered as a TAGGED word of
  its own kind (`_tagged_word_value`, emit_calls.py): `None` -> `mojo_box_none`,
  a float / bool -> its box, an int / pointer by value. So `next(it, None)` and
  `next(it, 2.5)` render as their values.
- Side effect (measured, not pinned as a goal): a str/int, bool/str or float/str
  mixed generator consumed by `next()` also now compiles through the tagged
  word. Measured against CPython on the default path: all match. (The stack-
  switch backend refused these mixed kinds before this round, per
  `_generator_value_kind`'s "mixed int / string yields" refusal; not re-measured
  on a HEAD snapshot for the default path.)
- Pins: `run_none_yield_tests` in `test_gimple_generator_runner.py`. The two
  `*_consumed_by_next_refused` refusal pins are replaced by
  `none_yield_consumed_by_next` / `bare_none_yield_consumed_by_next` (CPython
  oracle), and added: `none_yield_direct_next_and_default`,
  `mixed_str_int_yield_consumed_by_next`. Before the fix the three `next()`
  cases refuse or print the wrong value (checked on a HEAD snapshot); after,
  all 8 cases in the group pass.

**Known remaining gap (pre-existing, NOT changed here):** under the
`MOJO_CORO=cpp` escape hatch, `next()` on a mixed str/int or bool/str
generator prints a box's ADDRESS (`'1\n4378379896\n2\n'` where CPython prints
`1\ns\n2`). The same output is produced on HEAD, so this is the C++ emitter's
`next()` reader, not a regression from this round. The default path is the
one that is correct; the C++ path is reached only when the stack-switch
backend refuses the module.

**Still open (next steps, in order):**
1. Item 2 (explicit `yield None` beside str/float): still REFUSED by the C++
   typer (`mojo/backend_gimple/cpp_async.py`, the top-level None-yield refusal
   added in round 3). Next step: the `none` marker in `cpp_core.py`'s
   yield emission and `_cpp_tag_yield_sites` (cpp_async.py:322), so the C++
   path boxes a None with `mojo_box_none()` like the stack-switch path does.
   Until then it is an honest refusal, not a silent 0.
2. The `MOJO_CORO=cpp` `next()` reader (above): the C++ path's `next()` must
   box a tagged result the way `_lower_generator_next` does.
3. The C++ bare-yield emitter line (`cpp_core.py`, `co_yield (int64_t)0`) is now
   unreachable for a None yield; delete it in a cleanup.

**Gate note for the integrator (not run here, light-worker rules):** this
round widens which generators take the tagged word. Compare `stdlib-dylib`'s
`skip <module>:` count and `stdlib-syntax`'s `U` count before and after: a
str/int, bool/str or float/str generator consumed by `next()` used to be
refused (a move to source fallback) and now compiles, so a DROP in `skip` is
expected; a RISE in `skip` or `U` is a regression to bisect.

## Status (2026-11-01, third round, work/bug-codegen-a-bare-or-explicit-yield-of: refusal, not silent 0)

**Landed (behaviour change, measured before/after):** a None yield that the
tagged word cannot carry is now an honest refusal on BOTH compiled paths,
instead of compiling to the int64_t slot that prints `0`.
- `_generator_value_kind` (`mojo/middle/coro.py`): after the tagged-word
  decision, `has_none` with no tag refuses with "a None yield whose consumer
  is not a for loop / list() / comprehension". Reached by `next(it)` on a
  bare-yield generator, which printed `0` (CPython `None`).
- `cpp typer` (`mojo/backend_gimple/cpp_async.py`, next to the
  `cpp_value_slot_refusal` check): any top-level None yield in a generator
  refuses ("a None yield ... would print 0"). Needed because the stack-switch
  refusal alone sent the module to the C++ path, which still printed `0`.
- Pins: `none_yield_consumed_by_next_refused` and
  `bare_none_yield_consumed_by_next_refused` in `run_none_yield_tests`
  (`test_generator_refused`). Before the fix both FAIL ("expected a refusal,
  but it compiled"); after, both PASS. `test_gimple_generator_runner.py`
  357/0; `test_gimple_async_runner.py` 39/0.
- Fallback output is correct: `python3 fire.py run` on the `next(it)` program
  prints `1` / `None` (CPython: `1` / `None`), with and without
  `MOJO_CORO=cpp`.

**Open-item status after this round:**
- Item 1 (`next()`): the silent `0` is GONE, but `next()` on a None-yielding
  generator is now refused, not compiled. The real fix is still open: a
  None-aware `next()` reader that returns a boxed word (see the 2026-10-31
  notes below). Refusal is the interim, consistent with `_tagged_consumers_ok`.
- Item 2 (explicit `yield None` beside str/float): still refused by the C++
  typer, and now refused by the explicit check above too. Unchanged next step.
- Item 3 (`MOJO_CORO=cpp` bare yield prints 0): CLOSED. The C++ bare-yield
  emitter (`cpp_core.py` `co_yield (int64_t)0`) is no longer reachable for a
  None yield, because the typer refuses first. The emitter line is dead for
  this shape and can be deleted in a later cleanup.
- Item 4 (`_list_word_push` has no None arm): CLOSED. `_list_word_push` has
  two callers (`mojo_list_append_word`, `mojo_list_append_double_kinded`), and
  the `'n'` arm is in `mojo_list_append_word`, landed on 2026-10-31.
- `list(g())` and comprehensions over `g()` were measured this round and
  already MATCH CPython (they are tagged, `_tagged_consumers_ok` covers them).

**Gate note for the integrator (not run here):** the refusal moves any stdlib
module with a None-yielding generator consumed by a non-for consumer, or
compiled through the C++ path, from compiled to source fallback. Compare
`stdlib-dylib`'s `skip <module>:` count and `stdlib-syntax`'s `U` count before
and after; a rise in `skip` is expected only from these modules.

## Status (2026-10-31, second round, work/bug-codegen-a-bare-or-explicit-yield-of)

**Landed:** a for-loop variable from a tagged generator that is appended to a
list (`for v in g(): out.append(v)`) now keeps its None. Two sites:
`mojo_list_append_word` (runtime/fire_runtime.c) has a `'n'` arm that gives the
slot the list's None kind (`MOJO_KIND_NONE`), and the `.append` emitter
(`mojo/backend_gimple/emit_methods.py`, list append `else` branch) routes a
tagged-word argument (`av in gen._boxed_vals`) to `mojo_list_append_word`
instead of `mojo_list_append_int`, which stored the box's address. Pin:
`none_yield_appended_to_list_in_for_loop` in `run_none_yield_tests`
(`[1, None, 2]`, CPython oracle; FAILED `[1, 4315…, 2]` before, PASS after;
the four none-yield cases 4/0). Item 4 below is closed for the append path.

**Still open:** items 1, 2 and 3 below, and `list(g())`, comprehensions over
`g()`, and `next(g())` (not tagged; see item 1).

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
