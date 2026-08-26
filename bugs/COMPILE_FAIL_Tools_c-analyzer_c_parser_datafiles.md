# COMPILE_FAIL: Tools/c-analyzer/c_parser/datafiles.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_parser/datafiles.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1)

Fresh repro: unchanged single blocker — `read_decls:
unsupported for-loop iterable type: CallExpr` — i.e. `read_all, _ =
_get_format_handlers('decls', fmt)` followed by
`for decl, _ in read_all(infile):`, a loop whose iterable is a call
through a RUNTIME-SELECTED callback value. Re-examined this round:
resolving that callee would require threading "this local holds one of
these known function values" through tuple-unpacking assignment — a
callable-value tracking capability the scalar coroutine-body model
doesn't have (same family as the declared-callable-local case, but
flow-derived rather than directly assigned). Even past it, the
transitively-imported `c_parser/info.py` signature-race family (see
that doc) waits behind. No code change; doc re-verified. Still open.

## Status (updated 2026-08-25, branch fix/opencode-pkgutil — shared consumption-ordering fix landed; this file's remaining blockers are different and unchanged)

The shared "generator-consumption ordering" machinery this doc's
blocker #1 below was an instance of is now FIXED in shared source
(commit `9ea2749` on fix/opencode-pkgutil): gen_module's generator
retry loop runs to a fixed point instead of a hard-coded 3 passes,
both coroutine-body consumption paths pad omitted trailing args from
the consumed generator's registered param defaults instead of
refusing on arity, the direct generator-call path's silent non-zero-
offset default mispad (`prod(3)` against `def prod(n, step=10)` ran
compiled with step=0) is fixed, and refusal reasons are latest-wins so
the stale "defined LATER" text no longer masks a function's real final
blocker. Forward consumption of an ELIGIBLE later-defined generator
now works at any chain depth, verified end-to-end with compiled-path
runtime output (new tests in test_gimple.py +
test_gimple_generator_runner.py; gates 253/253, 76/76, selfhost clean,
stdlib dylib 0 skips).

Re-ran this file post-fix: **the failure set is UNCHANGED from the
2026-08-23 entry** — `iter_decls_tsv`'s forward consumption of
`_iter_decls_tsv` already resolved via retries even before this fix
(1 link < 4), and the module still aborts on exactly one of its own
generators:

```
cannot compile module: function(s) read_decls (generator function(s) ...)
Unsupported shape(s): read_decls: unsupported for-loop iterable type: CallExpr
```

Precise current shape: `read_decls` does
`read_all, _ = _get_format_handlers('decls', fmt)` then
`for decl, _ in read_all(infile): yield decl` — the loop iterable is a
call to a RUNTIME-SELECTED callback (`read_all` is not a statically
known sibling generator), which the coroutine body's for-loop lowering
has no representation for. That is a dynamic-callee consumption gap, NOT
the ordering constraint (ordering can never be the issue when the callee
isn't statically resolvable at all). The transitively-imported
`c_parser/info.py` scalar-only-yield render-method refusals also still
apply per that doc. All mechanisms remain within tracked
coroutine/ordinary-codegen gap families; doc kept open.

## Status (updated 2026-08-23 — failure shape changed: consumption-ordering refusal + ordinary-path GCC errors now surface)

Re-ran against current master tip (`626f3f0`). The two 2026-08-10
blockers below are superseded by a different, later-reaching failure
set (tuple-yield still holds; `_iter_decls_tsv`'s own tuple yield is no
longer refused):

1. `iter_decls_tsv` refuses with the consumption-ordering message —
   `for info, extra in _iter_decls_tsv(infile, extracolumns)` consumes
   a generator defined LATER in the module, and the coroutine drive-loop
   only supports generators already translated in an earlier pass:

```
[gimple_codegen] generator 'iter_decls_tsv' not eligible for C++
coroutine path, falling back to honest refusal: `for ... in
_iter_decls_tsv(...)` does not consume a generator this compile has
itself already translated via the C++20-coroutine path (either it's not
a generator this codegen supports, or it's defined LATER in this module
— the consumed generator must be defined earlier)
```

2. Independently, the ORDINARY (non-generator) GIMPLE path for this
   file's plain functions now reaches g++ and fails there:
   `write_decls` emits `invalid use of void expression`
   (datafiles.py:57) and `variable or field '_t13'/'_t16' declared
   void` (:60/:64); transitively-imported `c_parser/info.py:825` emits
   `non-trivial conversion in 'parm_decl'`. These are new observations,
   previously masked by the earlier generator refusals; not
   root-caused further this session.

The transitively-imported `c_parser/info.py` render methods also refuse
on their scalar-only yields ("every `yield` must carry a value, and all
values must agree on one scalar type"), same as that doc documents. All
mechanisms remain within the tracked coroutine/ordinary-codegen gap
families; doc kept open; not attempted.

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
