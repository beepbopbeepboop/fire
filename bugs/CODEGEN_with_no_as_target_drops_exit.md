# `with C():` with no `as` target never calls `__exit__` in the compiled path

## Status

**Open, unfixed.** Found on 2026-10-01 while replacing `build_stdlib_dylib`'s
`@contextlib.contextmanager` publish lock with a class (commit `ccd83a2b`): the
obvious spelling of the replacement silently never released the lock in a
self-hosted build. Worked around there by binding the value (`as _lock_fd`) and
by filing this, because the fix changes the generated C of every `with`
statement in every compiled module and that is a `make gate` change.

## The bug

`mojo/backend_gimple/emit_stmts.py::_gen_stmt_WithStmt` accumulates three
index-parallel lists per `with` item — `_ctx_ts` (the context-manager's C type),
`_ctx_vs` (its value), `_ctx_sns` (its struct name) — plus the two
generator-dispatch lists. `_with_emit_exits` walks them to emit each item's
`__exit__` call, and the `has_exit` pre-scan that decides whether the whole block
needs a `setjmp`-protected region reads `_ctx_sns`.

All five `.append` calls sit INSIDE the `if item.alias is not None:` branch:

```python
        if item.alias is not None:
            alias = _with_item_alias_name(item.alias)
            if alias not in gen.var_types:
                gen._declare_var(alias, enter_ret_t)
            gen._safe_coerce_emit(enter_ret_t, gen.var_types[alias], enter_v, alias)
            _ctx_ts.append(ctx_t)        # <-- only reached when there IS an `as`
            _ctx_vs.append(ctx_v)
            _ctx_sns.append(struct_name)
            _gctx_bases.append(None)
            _gctx_vs.append(None)
```

So `with ctx():` — no `as` — appends nothing. `has_exit` is False, no `setjmp`
region is emitted, and `_with_emit_exits` iterates an empty list: `__enter__` is
called, the body runs, and the teardown is never emitted at all. Not a wrong
`__exit__` argument, not a missing `mojo_exc_pop` — no teardown.

Measured on this tree, `compile_module_to_c` on a two-function module, same
class, only the `as` differing:

    with _OutputLock(out) as fd:   ->  __init__, __enter__, body,
                                        __exit__ (normal path), __exit__ (raise path)
    with _OutputLock(out):         ->  __init__, __enter__, body.   (no __exit__)

The generator-dispatch arm is NOT affected: it appends before the alias check, so
a `@contextmanager` generator used as `with g(x):` does get its final `resume()`
+ `destroy()`.

## Why it is worse than a leak

For the lock it was found on it is a self-hosted-build correctness problem, not
just a leak: a `with` on a lock object that never releases it wedges every other
process that wants the same lock for the life of the tree, in exactly the
cross-process situation the lock exists for. More generally, any resource with a
`__exit__` (a temp file, a transaction, a subprocess) leaks per iteration.

The interpreter is the reference and gets this right — real Python calls
`__exit__` for `with C():` — so this is a compiled-path-only divergence, and the
`test_runtime_diff.py` A/B engine comparison cannot see it either: the two
engines differ on the OUTPUT, and here the output can be identical (the body
worked) while the teardown never ran.

## Next step

Move the five `.append` calls out of the `if item.alias is not None:` branch, to
the same place the generator arm does them (right after `enter_v` is computed,
before the alias binding), so both spellings register the item. The `has_exit`
pre-scan and `_with_emit_exits` then need no change at all: they already consume
exactly these lists, and index-parallelism is already the convention the
generator arm established (the reason it is three lists and not a list of
tuples).

What to expect to move, and what to watch:

  * every `with X():` (no `as`) over a class with an `__exit__` in a struct the
    codegen knows gains a `setjmp` region and an `__exit__` call. That is the
    fix, but it is new `setjmp` in functions that had none, and
    `_func_used_setjmp` is what decides whether a method keeps its `__GIMPLE`
    tag (`emit_funcs.py:3855`) — so the generated C for some methods will change
    signature-level, not just body-level.
  * the `stdlib-dylib` `skip` count and `compile_stdlib.py`'s unexpected-failure
    count are the two numbers CLAUDE.md names for this class of change; both
    should be compared before/after.
  * a regression belongs beside the other `with` cases in `test_gimple_runner.py`
    (it compiles and RUNS, which is what proves the teardown happened: write a
    `__exit__` that prints, and require the line in stdout, once with `as` and
    once without).
