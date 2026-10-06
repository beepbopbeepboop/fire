# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
