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

## Row 1 (`dis._parse_varint`, a list iterator passed to a function): FIXED 2026-10-31

An `iter(<list>)` local that is passed to a user function is now a runtime list-iterator WORD
(`mojo_listiter_new`, runtime/fire_runtime.c; `next(w)` -> `mojo_next_word`, `for x in w` -> `mojo_iter_word`),
so the callee and the caller consume it from one position. The decision is shared by the caller's binding
(`emit_stmts._try_bind_iter_cursor`), the `for` lowering (`emit_loops`) and the callee's parameter typing
(`module_gen._static_arg_container`) through `itcursor.name_is_escaping_iter`; `next` is no longer
"iteration evidence" for a parameter's type (`infra_infer._ITERABLE_CONSUMING_BUILTINS`), since an
iterator is not a list. Test: `gimple_list_iterator_crosses_a_call` in `test_gimple_runner.py`.
Limits, both loud: an iterator over strings/floats passed to a function still refuses at compile time
(the kind is lost through the returned word), and a list iterator and a generator through the SAME
parameter crash at run time on master as well (pre-existing, separate).

## Update (2026-10-31, closure probe on a clean path)

`tools/probe_coro_close_refusal.py` on `import mailbox` against a COPY of the 3.14.6 `Lib` (a directory name
whose case matches the resolved one; on macOS `lib` vs `Lib` is the same directory, and the module was then
registered under two spellings): master 59 `# ERROR: compiling imported module` lines, 13 of them
"N overloads ... referenced as a plain value" (`reprlib`, `inspect` x4 with 2/3/5/7, `locale`, `_parser`).
Cause: a struct's method signatures were `.append`ed on every compile of its module, so a module retried
against the shared gen after a rollback multiplied its methods into fake overloads. Registration is now
idempotent per overload id (`module_gen`, test `recompiling_a_struct_does_not_multiply_its_method_overloads`);
the same probe on the fix shows 0 overload refusals and 52 errors.

What is left in the closure, by module (each its own feature, none a one-line fix):
`collections`/`enum` run-time 3-argument `type(...)`; `dis`/`typing`/`inspect`/`selectors` module-level
`namedtuple` forms beyond `Name = namedtuple("Name", [literals])`; `functools`/`_win_cp_codecs`/`_bootstrap`
a class declared inside a function that captures locals (`bugs/CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`);
`dataclasses`/`traceback` `match` or-patterns and class patterns; `signal` a decorator inside a module-level
block; `weakref` `d.pop(key, default)` with a list default on an int-valued dict.
