# COMPILE_FAIL: Tools/c-analyzer/c_parser/datafiles.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; other, pre-existing gaps now block)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Confirmed via an isolated compile: BOTH `_iter_decls_tsv`'s
`yield declinfo, extra` and `iter_decls_tsv`'s `yield decl, extra` are
no longer refused, and each one's own tuple-boxing/`co_yield` text is
syntactically valid C++.

**This file still does not build**, blocked by two separate,
pre-existing gaps, unrelated to tuple-yield:
1. `iter_decls_tsv`'s own body does `for info, extra in
   _iter_decls_tsv(infile, extracolumns):` — a plain `for` loop, inside
   a coroutine body, consuming ANOTHER compiled generator, with a
   non-`enumerate()` tuple target. `_cpp_for_stmt` only special-cases a
   tuple target for `enumerate(...)`; this shape falls through to
   `for (auto info, extra : _iter_decls_tsv_1ce6ce(...))` — malformed
   C++. Confirmed as the SAME gap independently found in `calendar.py`'s
   and `weakref.py`'s own generators (see those docs).
2. `relroot != fsutil.USE_CWD` / `os.path.abspath(relroot)` /
   `_info.Declaration.from_row(info)` — module-attribute references
   (`fsutil.USE_CWD`, `os.path.abspath`, a bare `_info` module
   reference) with no lowering in the coroutine-body expression emitter.

Neither is the promise/ABI gap this session's fix targets. Not
attempted here. The four `info.py`-cascade candidate mechanisms
originally documented below remain UNVERIFIED either way (still
unreached — masked now by these two gaps instead of the tuple-yield
refusal). Doc kept open (not deleted).

## Status (re-verified 2026-08-09)

Re-ran against current master (`python3 mojo.py build .../c_parser/
datafiles.py`). The previously-documented 472-error cascade rooted in
the transitively-imported `c_parser/info.py` no longer surfaces — NOT
because those four candidate mechanisms were fixed, but because this
file now fails much earlier in the pipeline, on its OWN generator
functions, before `gen_module` ever gets far enough to elaborate the
`info.py` import chain that produced that cascade:

```
Error building: cannot compile module: function(s) _iter_decls_tsv,
iter_decls_tsv (generator function(s), contain a `yield`/`yield
from`) — ...
```

With `MOJO_DEBUG=1`:

```
generator '_iter_decls_tsv' not eligible for C++ coroutine path,
falling back to honest refusal: _iter_decls_tsv: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)

generator 'iter_decls_tsv' not eligible for C++ coroutine path,
falling back to honest refusal: iter_decls_tsv: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```

`_iter_decls_tsv` (line 105) does `yield declinfo, extra` (line 117);
`iter_decls_tsv` (line 85) does `yield decl, extra` (line 91) — both
2-tuple-valued yields. This is the same already-tracked "coroutine
codegen has much weaker yield/type coverage than the ordinary function
path" gap independently confirmed this session for `c_analyzer/
__init__.py`, `c_analyzer/__main__.py`, `c_analyzer/info.py`,
`c_common/scriptutil.py`, and `c_common/tables.py`. Not attempted here
— deliberately deferred, already-tracked compiled-generator/async-
codegen project scope, not a narrow fix.

The four `info.py`-cascade candidate mechanisms previously documented
below are UNVERIFIED, not confirmed fixed — they're simply unreachable
now from this file's top-level compile, masked by the earlier (and
more correct) generator refusal. `bugs/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
plausibly hits `info.py` more directly and may still be a better entry
point for a dedicated follow-up on those four candidates, if `info.py`
gets pulled into this session's scope. Original candidate list kept
verbatim below for that follow-up:

1. The same "function-as-value at module scope" gap already documented
   in `bugs/COMPILE_FAIL_importlib__bootstrap_external.md` (the
   `_funcptr_*` GCC suggestion is the same tell).
2. `HighlevelParsedItem` (in `info.py`) subclasses namedtuple factories
   AND defines its own `__getattr__` override (dynamic attribute
   fallback: `def __getattr__(self, name): return self._extra[name]`)
   — plausibly related to `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`.
3. `__str__` does `self._str = next(self.render())` where `render()` is
   a generator method — same `next()`-on-a-generic-iterator shape
   flagged (at the time) in `bugs/COMPILE_FAIL_importlib_resources__common.md`;
   that doc no longer exists in the current tree (deleted as fixed or
   superseded by other work) — not re-verified here.
4. `HighlevelParsedItem.id` property (`return self.parsed.id`) reads a
   field through a chain that ends up typed `MojoBoundMethod *` instead
   of the real class — plausibly the struct-field/return-type
   inference gap this session's other hard bugs already describe.

(The old GCC-warning-log excerpt previously shown here was from the
stale pre-hardening repro described above and has been removed —
current repro fails before GCC is ever invoked.)
