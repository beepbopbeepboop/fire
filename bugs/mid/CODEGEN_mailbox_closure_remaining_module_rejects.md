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

## Next step

One fix per row, each with its own quick test against CPython output:
1. `dis._parse_varint`: `next(it)` where `it` is a name bound to a list iterator held as `MojoList *`
   (lower `next(<list-cursor local>)`, or find why `iter(list)` lost its cursor kind).
2. `functools.cmp_to_key` / `_win_cp_codecs`: a class declared in a function that captures the
   function's locals (closure-class capture).
3. `reprlib`: an overloaded method referenced as a plain value.
4. `collections/__init__.py`: run-time 3-argument `type(...)` (namedtuple's `type(typename, (tuple,), class_namespace)`).
Re-run the probe after each; the count of `# ERROR: compiling imported module` lines is the metric.
