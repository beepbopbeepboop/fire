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

- Rows 2-3 of the table (`functools`, `encodings/_win_cp_codecs`) were the nested-class
  enclosing-local read bug, FIXED 2026-11-01 (`_gmi_capture_nested_class_enclosing_reads`; also user-struct
  `<`/`>=` dunders now dispatch). Re-probe to see what those modules hit next.
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
a class declared inside a function that captures locals (FIXED 2026-11-01, re-probe);
`dataclasses`/`traceback` `match` or-patterns and class patterns; `signal` a decorator inside a module-level
block; `weakref` was `d.pop(key, *args)` with the packed list taken for the default (FIXED 2026-10-31, `gimple_dict_pop_with_spread_default`; re-probe for what weakref hits next).

## Update (2026-11-01): `match` or-patterns

`dataclasses.py`'s `case Format.VALUE | Format.FORWARDREF | Format.STRING:` no longer refuses: in a Python source
the lowering flattens `A | B | C` into the alternatives its arm chain already tests (`emit_stmts._flatten_or_patterns`;
a `.mojo` source keeps the switch-style reading and the refusal). Found on the way, fixed, and tested
(`gimple_return_type_through_match_arms`): a function whose only `return`s are inside `match` arms was typed from
no return statement and handed back 0 for a string. Still refused in that closure: `traceback.py`'s class patterns
(`case ast.Return(value=ast.Call()):`), module-level `namedtuple` built from non-literals, `type(...)` with three
arguments, a class declared in a function that captures its locals, a decorator inside a module-level `if`.

## Update (2026-11-01, probe after the nested-class and property fixes)

Probe: `/tmp`-style dir holding a copy of the 3.14 `Lib` plus `entry.py` = `import mailbox`,
`python3 tools/probe_coro_close_refusal.py entry.py --do-imports` (an entry WITHOUT the Lib copy beside it
compiles "OK" at 0.1 GB because nothing is resolved; that is not a clean closure). Result: 59 -> 15
`# ERROR: compiling imported module` lines. What they are now:

- `functools`: `decorator 'wraps(...)' on 'wrapper' returns int64_t (not callable)` (the old nested-class wall is gone, this is the next one).
- `dis` / `inspect`: non-literal `namedtuple(...)` (by-design refusal, see above).
- `importlib/_bootstrap`: was `ModuleSpec.has_location` 2 overloads = a `@property` with `@x.setter`. FIXED
  (`_gmi_rename_property_setters`: the setter becomes `__setprop_x`, `obj.x = v` calls it); also fixed in
  passing: a `@property` READ printed the bound-method pointer and `==` compared two such pointers.
- `tokenize`, `annotationlib`, `dataclasses`, `traceback`: `No module named 'formal'` / missing `fire_compiler.py` —
  the probe's cwd/path, not a compiler defect (run it from the repo root).
Next: the `@wraps(...)` decorator wall, then `namedtuple` from non-literals, then 3-arg `type()`.

## Update (2026-11-01, functools: walls found by bypassing each refusal in turn)

Compiling a copy of `functools.py` alone (`python3 fire.py build functools_copy.py`), bypassing one refusal at a time:

1. `@wraps(f) def wrapper` refusal (`_gmi_refuse_scalar_decorator_rebind`: `wraps` returns `partial(update_wrapper, ...)`,
   inferred int64_t). Using `functools.wraps` from USER code already works (`g(5)` -> 11); this is only the same-module
   `wraps`. Real fix = apply `wraps(f)(wrapper)` as a decorator whose factory returns a `partial` object, which needs
   (a) the module's own `class partial` (`__new__`/`__call__` with `*args, **kwargs`) compiled, and (b) `update_wrapper`'s
   attribute copying (`setattr` on a function: `_func_attrs`). Treating `wraps` as identity was rejected: it drops
   `__wrapped__`/`__name__`/`__doc__` silently.
2. FIXED here: `_CacheInfo = namedtuple("CacheInfo", (...))` (typename != bound name, tuple of literals) now lowers; the
   class is declared under the bound name and the repr shows the typename.
3. NEXT WALL: `_CacheInfo(hits, misses, maxsize, currsize)` with non-literal arguments: the namedtuple lowering types a
   field only from literals. Untyped fields are NOT an answer: `maxsize` is `int | None` and the word ABI prints a None
   as `0` (see bugs/mid/CODEGEN_a_none_held_in_an_int64_local_is_indistinguishable_from_zero_in_membership.md). The route is
   typed fields from the call-site argument types, resolved by the codegen (not by `fire_compiler.desugar_namedtuples`,
   which runs before types exist).

Also fixed on the way: `print(x)` of a user struct printed its address as a decimal; it is now `__str__`, else
`__repr__` (test `gimple_print_user_struct_dunder_repr`).
