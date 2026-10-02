# COMPILE_FAIL: Tools/c-analyzer/c_analyzer/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
