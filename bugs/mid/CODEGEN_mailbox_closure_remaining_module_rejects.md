# CODEGEN: the mailbox whole-closure still rejects these modules (the `_coro.close()` wall is gone)

## Status (2026-10-31, OPEN, measured)

`tools/probe_coro_close_refusal.py` on the real Python 3.14.6 `Lib` (copied beside the entry,
`import mailbox`, `do_imports=True`, `memslot --gb 8`): every read of `_coro` in
`_collections_abc` now carries its generator api (`api_table=True`, ctype
`MojoGenerator *`, `poisoned=False`). The old first wall (`generator .close() on a value with no
known generator API`) no longer fires; the fix landed in `c2679ae30` (key the generator-global api
by defining module). The closure is still not clean. The `# ERROR: compiling imported module`
lines, in the order the probe printed them:

| module | refusal |
|---|---|
| `collections/__init__.py` | 3-argument `type(name, bases, namespace)` creates a class at run time |
| `reprlib.py` | method `Repr.repr` has 2 overloads and is referenced as a plain value |
| `functools.py` | method `__lt__` of class `K` reads `mycmp`, a local of `cmp_to_key` (class declared in a function cannot reach the enclosing function's locals) |
| `encodings/_win_cp_codecs.py` | same shape: `encode` of `IncrementalEncoder` reads `cp` of `create_win32_code_page_codec` |
| `dis.py` | `next(...)` on `next(IdentExpr)` (receiver typed `MojoList *`) in `_parse_varint` has no lowering |

(The probe was stopped after these; later modules were not reached.)

## Update (2026-10-31, later)

- Rows 2-3 of the table (`functools`, `encodings/_win_cp_codecs`) are the existing
  `bugs/CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`; do not duplicate the work here.
- `reprlib.py` compiles standalone on master (`compile_to_gimple` OK) and its module-scope
  `repr = aRepr.repr` now lowers correctly (two silent miscompiles found and fixed on the way: a module-scope
  binding of a builtin name was ignored, and a module-scope bound-method global lost its return type). The
  "2 overloads" refusal is therefore closure-contextual: re-run the probe to see whether it still fires.

## Next step

One fix per row, each with its own quick test against CPython output:
1. `dis._parse_varint`: `next(it)` where `it` is a name bound to a list iterator held as `MojoList *`
   (lower `next(<list-cursor local>)`, or find why `iter(list)` lost its cursor kind).
2. `functools.cmp_to_key` / `_win_cp_codecs`: a class declared in a function that captures the
   function's locals (closure-class capture).
3. `reprlib`: an overloaded method referenced as a plain value.
4. `collections/__init__.py`: run-time 3-argument `type(...)` (namedtuple's `type(typename, (tuple,), class_namespace)`).
Re-run the probe after each; the count of `# ERROR: compiling imported module` lines is the metric.

## Design guide for row 1 (`dis._parse_varint`: a list iterator passed to a function)

Minimal repro (CPython prints `4229` then `3`-ish; use data that does not exhaust):

    def pv(iterator):
        b = next(iterator); val = b & 63
        while b & 64:
            val <<= 6; b = next(iterator); val |= b & 63
        return val
    def main():
        it = iter([1, 65, 3, 9]); print(pv(it)); print(pv(it))

Compiled: `cannot compile module: next(...) on next(IdentExpr) (receiver typed MojoList *) in function pv`
(emit_calls.py ~2979 refusal).

Why: `it = iter(<list>)` is lowered to a C-local CURSOR record (`gen._list_iter_cursor[cname]`,
`emit_stmts.py` ~285-320; consumers `emit_calls.py:2755` `next(it)` and `emit_loops.py:876` `for x in it`).
The cursor is a C temp, not a value, so it cannot cross a call: the callee sees the bare `MojoList *`.

Plan (runtime object + call-site boxing + sync-back; callee needs no new lowering because
`next(<word>)` already goes through `mojo_next_word`, runtime/fire_runtime.c ~14868):
1. runtime: `MojoListIter {MojoList *l; int64_t pos;}`, `mojo_listiter_new(l, pos)` (registered like
   `_reg_box`), `mojo_listiter_pos(w)`, and a list-iterator arm in `mojo_next_word` (element via
   `mojo_list_get_boxed`; exhaustion raises the same tagged StopIteration as the generator arm; `has_default`
   returns `dflt`). Declare in fire_runtime.h and bump the ABI census (`rthdrscan`, `FORMAL.md`).
2. codegen: in the user-function call lowering (`_lower_named_call`, where `arg_pairs` is built, cf.
   `ginf._tag_mixed_list_call_args` at emit_calls.py:8854), for an argument that is an `IdentExpr` with
   `itc.cursor_for(gen, gen._cname(name))`: pass `(int64_t)mojo_listiter_new(src, cursor)` instead, and after
   the call emit `cursor = mojo_listiter_pos(obj)` so the caller's cursor sees the callee's consumption.
   The callee parameter is then inferred `int64_t` from the call-site arg type (same as any word param).
3. tests: the repro above in `test_gimple_runner.py` (stdout vs CPython: both calls), a callee that exhausts
   (`StopIteration` caught by the caller), `next(it, default)` through the callee, and `for x in it` in the
   caller after the callee consumed some. Gate: compile_stdlib.py must keep 0 unexpected failures; re-run
   `tools/probe_coro_close_refusal.py` on the mailbox closure and watch the `dis` line disappear.
