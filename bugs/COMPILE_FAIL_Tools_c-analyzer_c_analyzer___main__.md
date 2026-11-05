# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-29 (round 3) — D3 measured: the coroutine path is the live emitter

Step 0 of the planning round 2 guide, run on this branch with a 6-line repro
(`.tmp/d3/repro.mojo`: `build_section(name, n)` defining `render` that yields
`f'{name}:{i}'`, consumed by `for x in render()`), via
`MOJO_DEBUG=1 python3 tools/memslot.py --gb 8 --label d3 -- python3 fire.py build -o .tmp/d3/out .tmp/d3/repro.mojo`
(exit 1, ~8 s):

    [gimple_codegen] generator 'render' not eligible for C++ coroutine path (retry pass 2),
      falling back: is a nested generator that reads enclosing-scope variable(s) n, name;
      the coroutine path has no capture model for a generator defined inside another function

So a nested sync generator is routed to the C++ coroutine path (the cpp_async lane), and
the capture refusal is what stops it there. No second emitter is involved, and nothing
on this tree routes the case to A3 `gimple_gen_coro.py`. D3 is answered: implement the
capture model in `cpp_async.py`, as the plan below says. The module still refuses with
the same "Unsupported shape(s)" text, so this round changed no behaviour and touched
no code. The capture model stays blocked on the nested-generator claim, as described below.

## Status 2026-10-29 (planning round 2) — capture-model design guide; no code landed this round

**Why no code.** The capture model lives in `cpp_async._gen_cpp_generator_unit`
(`mojo/backend_gimple/cpp_async.py:310`), the same nested-generator lane as
`bug:CODEGEN_nested_generator_yield_type_and_delegation`, which another worker
holds (`control.py claims`). Editing it here would violate the claim, so this
round records the plan instead. Also: even the full capture model does NOT close
this file, so the file's own DONE is blocked on other claims (see "Blockers").

**Current state, measured on this branch.** The refusal from the entry below is
present: `_nested_generator_captures` (`cpp_async.py:1218`), its check in
`_gen_cpp_generator_unit` (`cpp_async.py` ~line 411, raises
`_UnsupportedGeneratorShape`), wired at `module_gen.py:3423`. Regression tests:
`run_nested_generator_capture_tests` (`test_gimple_generator_runner.py:2116`).
I did not re-run that file this round (no code touched); the 265/0 figure is the
2026-10-29 entry's.

**Blockers for `__main__.py`, all must clear.**
1. Capture model for nested sync generators (this guide) → `render` compiles.
2. `for line in _render_table(...)` target not typed in `_cpp_for_stmt`
   (`cpp_core.py:6279`) → claimed nested-generator lane.
3. Module-attribute value read stubbed to `0` in a generator body (shared with
   `bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md`, `iter_marks`).
4. `_fix_write_default`, `_parse_next_local_static`, `_parse_struct_next`: yield
   sites agree INTERNALLY but call sites disagree on the yielded type. Unexamined
   third yield-typing shape. Measure with `MOJO_DEBUG=1` before designing.
5. Imported-module floor `c_parser/info.py`, `c_parser/parser/_func_body.py`,
   `c_parser/match.py` → `bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md`
   (claimed by another worker).

**Decisions the capture model needs (recommendations).**
- **D1, value vs cell.** Python closures read the enclosing VARIABLE, so a
  rebind after the nested `def` is visible to the generator. A by-value snapshot
  is correct only when every captured name is bound exactly once in the enclosing
  def, before the nested `def` statement. Recommendation: snapshot in that case;
  otherwise keep the refusal. Counting bindings is cheap via the existing
  `_helper_bound_names` walk. Heap-boxed cells (the A3 capture-box /
  `_nested_async_capture_plan`, `mojo/middle/coro.py:4785`) are the follow-up for
  multi-binding captures, not this round.
- **D2, where the snapshot lives.** `build_section` `return`s `render`, so the
  generator OUTLIVES its enclosing frame, and a call `render()` in `main` has no
  access to `name`. Passing captures as call arguments is therefore WRONG for
  this shape. The snapshot must be carried by the generator handle, i.e. an env
  object allocated at the nested `def` statement, the same job `ClosureInfo`
  (`gimple_codegen.py`, imported at `module_gen.py:82`) does for closures. A
  generator consumed only INSIDE its enclosing def (no escape) may take captures
  as plain parameters; that cheaper case is a valid first step if the escaping
  case is deferred.
- **D3, which emitter is live.** `cpp_async.py` is still 3169 lines even though
  the memory notes say A3 replaced the C++ emitter. Step 0 of the next round is a
  measurement: `MOJO_DEBUG=1 python3 fire.py build` on a 6-line repro, to see which
  emitter a nested sync generator takes on this tree. Do not implement before that.

**Implementation plan (after D3 is measured and the lane claim is clear).**
1. `cpp_async.py`: in `_gen_cpp_generator_unit`, for captured names that pass the
   D1 single-binding check, derive each capture's C++ ctype from the enclosing
   def's declared types (not just names, which `_helper_bound_names` gives). Keep
   the refusal for everything else, with the same message text.
2. Thread the env (escaping case) or parameters (consumed-inside case) through
   the generator's `param_ctypes` path (`cpp_async.py` ~line 400) so the body
   reads `env->name`, not the bare name.
3. Leave `_nested_generator_captures` as the single detector; do not add a second.

**Tests that prove it.** In `test_gimple_generator_runner.py`:
- Convert `nested_generator_reads_enclosing_param_in_fstring_refused` (line 2125)
  from "refused" to a RUN-COMPARE case: `build_section('x', 2)` followed by
  `for x in render(): print(x)` must print `x:`, `row`, `row`, identical to
  `python3 fire.py run` on the same text (the `test_interp_oracle.py` pattern).
- Add: escaping local capture (single binding) → run-compare; consumed-inside
  generator → run-compare; a capture REBOUND after the nested `def` → still
  refused (pins D1).
- The two run-compare cases fail before the change (refused, not run) and pass
  after. The rebind case passes both before and after: it pins the refusal, so
  a later widening of D1 cannot slip through silently.

**Unknowns the next round must not re-investigate.** None of the above is measured
on the compiled output yet except the refusal itself. The first run of the
run-compare tests is the first real evidence for D2.

## Status 2026-10-29 — partial: a nested generator that reads an enclosing variable is now an honest refusal, not a g++ error

**Root cause, measured.** `render` is defined INSIDE `build_section(name, n)` and reads
`name` and `n` (`yield f'{name}:'`, `range(n)`). The generator set is built with
`_walk_ast`, which walks into nested defs, so `render` was lifted as a free top-level
generator with no capture model. Its coroutine body then named `name`/`n` at file scope
and g++ rejected the generated .cpp ("'name' was not declared in this scope"), blaming
generated code. The f-string reads were invisible to the free-name walk, because the
parser keeps an f-string as one raw `StringLiteral`.

**What landed.** `cpp_async._nested_generator_captures` finds every generator defined
inside another `def` that reads a parameter or local of an enclosing `def` (f-string
fields included). `_gen_cpp_generator_unit` refuses such a generator with
`_UnsupportedGeneratorShape`, so the module gets the normal "Unsupported shape(s)"
refusal naming the variables instead of a g++ failure. Regression tests:
`run_nested_generator_capture_tests` in `test_gimple_generator_runner.py` (fail before,
pass after; the file runs 265/0).

**What did NOT change.** `render` still does not compile. The real fix is a capture
model for a generator frame: thread the enclosing variables into the coroutine (as the
A3 capture box does for nested async defs in `mojo/middle/coro.py`) and make the
generator read them through that box. That is the one remaining piece for this file,
and the `section`/`render` refusals stay until it lands.

**Re-measured and not the cause.** A minimal `for line in table(n): yield line` inside a
nested generator, consumed by a top-level one, compiles and matches the interpreter byte
for byte, so the "for-loop target is never typed" diagnosis does not reproduce on a
module-level generator. The nested-generator yield-type CODEGEN entry that the 2026-10-01 diagnosis cited
is no longer in the tree.

**Next step.** Capture model for nested sync generators (see above), then re-run this
file; `_fix_write_default`/`_parse_*` yield-agreement refusals are separate and unexamined
on this tree.

## Status 2026-10-04 — the two blockers are still the two, but the refusal LIST behind them is longer than this entry records, and one shape in it is new

Re-measured on this tree (`python3 fire.py build -o .tmp/out .tmp/ca/c_analyzer/__main__.py`,
sources from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, arm64, ~8 s).

`render`'s mixed yields are STILL refused, and the diagnosis in
`bugs/CODEGEN_nested_generator_yield_type_and_delegation.md` (which this entry points at,
and which is the right place for the mechanism) has not been acted on: the `for`-loop
TARGET's type is still not looked up, so `yield ''` types `char *` while the loop over
`_render_table(...)` leaves `line` at the `int64_t` default and the same-type check refuses.
Nothing from that entry's two measured steps has landed, deliberately — it explains why
landing them without the capture work is a net loss in diagnosis, and that still holds.

**Two measurements that are new.** First, `MOJO_DEBUG=1` shows this file's generator refusal
list is LONGER than the two this entry names, and one shape in it is not in this file's text
at all:

    _fix_write_default:        yields ['empty'], whose call sites do not all pass the same
                               statically-known type
    _parse_next_local_static:  the same shape, `yields ['srcinfo']`
    _parse_struct_next:        the same shape, `yields ['parent', 'srcinfo']`
    _iter_filenames:           a call to unresolved callee 'process(...)'  (shared with
                               bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md)

`yields [...], whose call sites do not all pass the same statically-known type` is a THIRD
yield-typing answer, distinct from both this entry's `render` case ("the yields disagree")
and the "a `for` target was never typed" case: here each yield site agrees INTERNALLY and
the SITES disagree. So a next session gets three distinct yield-typing failures to tell
apart before touching any of them, and the third is the one this entry never mentions.

Second, `section`'s `for ... in render(...)` is still downstream of `render`, exactly as the
2026-10-01 entry says — and the ordering loop still runs to a fixed point, so the message is
still whatever the LAST attempt was. Do not read it as an ordering bug.

## Status 2026-10-01 — unchanged; both blockers re-measured, and the diagnosis below is CONFIRMED and sharpened

Re-measured on the current tree (`python3 fire.py build`, sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`):

```
Unsupported shape(s):
  render: render: every `yield` must carry a value, and all values must agree
    on one scalar type (int64_t/double/_Bool)
  section: `for ... in render(...)` does not consume a generator this compile
    has itself already translated via the C++20-coroutine path
```

Byte-identical to the entry below. This session worked the `render` half and
**confirmed its root cause and then went further than the entry below
believed was reachable**, so the finding is recorded in full, with the two
steps that were measured to work and the one that is the real feature gap, in
`bugs/CODEGEN_nested_generator_yield_type_and_delegation.md`:

* `render`'s mixed yields are NOT a module-attribute read stubbed to 0 (this
  doc's guess). They are a `for`-loop TARGET whose type is never looked up:
  `yield ''` types `char *`, `for line in _render_table(...)` leaves `line` at
  the `int64_t` default, and the same-type check refuses. The answer already
  exists twice — `_yield_from_delegate_ctype` computes it for the
  `yield from` spelling, and `_cpp_for_stmt`'s delegate branch declares the
  loop target from it — so this is a missing lookup, not a widened guess.
* behind it, `_cpp_iterable_is_delegatable_generator_call` cannot see a
  TOP-LEVEL generator's original name at all, because
  `_all_generator_names` is built from the POST-DESUGAR AST where the A3
  stack-switch desugar has already renamed it `__mgco_<name>_body`.
* past that, a nested generator consuming a top-level one needs the
  enclosing parameters CAPTURED into the coroutine frame, and nothing does.

Nothing landed from this session's work on it, deliberately: the two steps
that were measured to work change which shapes reach a path that then fails
with a g++ error naming an internal symbol, which is a net LOSS in diagnosis
until the capture work lands with them.

The `section` line is still the last attempt's reason, not an independent
blocker — the entry below's advice to fix `render` first is correct.

## Status 2026-09-30 — unchanged; both of this file's blockers are shared with other c-analyzer files

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`):

```
Unsupported shape(s):
  render: render: every `yield` must carry a value, and all values must agree
    on one scalar type (int64_t/double/_Bool)
  section: `for ... in render(...)` does not consume a generator this compile
    has itself already translated via the C++20-coroutine path (either it's not
    a generator this codegen supports, or it's defined LATER in this module —
    the consumed generator must be defined earlier)
```

Nothing this session moved either. Both are the SAME root as blockers
documented in the sibling docs, which is why they belong in one follow-up:

### `render`'s mixed yield types — same root as `c_common/scriptutil.py`'s `iter_marks`

`mojo/backend_gimple/cpp_async.py`'s `_generator_yield_ctype` refuses because
the yields disagree on type, and the disagreement comes from a MODULE-ATTRIBUTE
VALUE READ the cpp body model stubs to `0`:

```
[gimple_codegen] stubbed operation: generator-body module-member value read ...
```

`c_common/scriptutil.py`'s `iter_marks` does `div = os.linesep`; this file's
`render` reads module attributes the same way. One fix — teach the coroutine
body model to read a module constant's real value (the per-module globals
structs already exist and are already emitted) and give
`_infer_simple_expr_ctype` the matching row — clears both, and is the
difference between an honest refusal and a program that computes `''` where
CPython computes `'\n'`. See `bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md`
for the detail and the "silent-wrong upstream" argument. **Start there**, not
here: this doc's refusal is downstream of the same stub.

### `section`'s "defined LATER" — the consumption-ordering family, still open

```
for ... in render(...)
```

The retry loop that runs to a fixed point
(`mojo/backend_gimple/module_gen.py`'s generator eligibility passes) exists
precisely for this and has already fixed the shallow chains it documents. It
has NOT fixed this one, and the message is the misleading kind the loop's own
"latest-wins" comment warns about: the reason recorded for a still-pending
generator after every pass is a SHAPE it genuinely fails on, reported here
under the ordering text.

Do not re-run the ordering machinery hoping for a different answer — it runs
to a fixed point already, so this refusal is stable by construction. The
ordering message is what the LAST attempt happened to be, and the real
blocker behind it is whatever `_gen_cpp_generator_unit(render)` raises once
`render`'s own shape is fixed. That is: **fix `render` first and this message
will change to the true blocker.** Until then it is not independently
diagnosable, and treating it as an ordering bug would be chasing the
`c_parser/parser/__init__.py`-class "downstream symptom" trap.

### Next step

1. Module-attribute value reads in a generator/coroutine body (shared with
   `c_common/scriptutil.py`) → clears `render`.
2. Re-run this file and read `section`'s message again; it is only meaningful
   once `render` compiles.
3. Then re-check the imported-module floor — `c_parser/info.py`,
   `c_parser/parser/_func_body.py` and `c_parser/match.py` still fail in this
   closure (see `bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md`),
   so clearing `render` alone will not make this file build.
