# CODEGEN: calling a nested `def` fetched from a container answers 0

Found 2026-10-02 while closing the nested-`def` half of
`CODEGEN_closure_env_and_boxed_local_never_freed.md`. Filed separately because
it is NOT a leak and NOT that fix's escape analysis: the value is stored
correctly and the failure is that the environment never reaches the slot, so the
call has nothing to dispatch on. Fixing the env's lifetime would not touch this.

## Status (2026-10-02 — reproduced on the current tree; not fixed)

## The shape

```python
def keep(kept, base):
    def inner(x):
        return x + base
    kept.append(inner)
    return inner(1)

kept = []
print(keep(kept, 10))     # 11  -- correct
print(len(kept))          # 1   -- correct
print(kept[0](5))         # 0   -- WRONG, want 15
```

Every part of it that does not involve calling through the container is
right. CPython prints `11`, `1`, `15`.

## Why it is not the env leak, structurally

The nested `def`'s environment is allocated once, at the `def` STATEMENT, and
owns the capture:

```c
  _env_inner = _alloc_keep_inner_env ();
  _env_inner->base = _t1;
  mojo_list_append (kept, <fnptr or bound method>);
  _t2 = keep_inner (_env_inner, _t3);   /* direct call, works */
```

and nothing ever writes `_env_inner` into `kept`'s element. So the slot holds a
callable with no environment attached, and calling it dispatches with nothing to
pass as `_env`. The value in the slot is therefore worth looking at directly
before designing anything: if it is the lifted function's plain name (a bare
`static` fnptr, no `MojoBoundMethod`), the fix is "the container's element has
to be a bound method over the env", which is a codegen question about
`append`/`__setitem__` on a callable; if it IS a `MojoBoundMethod` whose `self`
is wrong, the question is where `self` got lost.

### Related, and NOT to be re-derived as a fresh bug

`bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`'s OPEN 2 is the
`{mut}`-capture BOX (`malloc(8)` per call, per variable) leaking. It is a
different allocation on a different path and it is a leak, so the two do not
share a fix. They do share a root: a callable's environment is a value this
backend has no uniform story for, and both holes are what falls out of that.

## Next step

Dump the generated C for this shape and read what `_env_inner` was appended as
(above — one line of `emit_calls`'s append lowering, or
`_gen_stmt_CallExpr`'s `append` arm). Then decide between:

- **append a `MojoBoundMethod` over the env**, which is the shape the
  capturing-lambda fix already has working end to end
  (`mojo_closure_free` + `mojo_cleanup_push_closure` + the
  `ownership_destruct.lambda_value_owned` escape rule), or
- **keep the raw fnptr and carry the env in a parallel slot**, which needs a
  container element type that exists for this and does not today.

The first is the smaller change and reuses a landed mechanism; the second is
what makes `kept[0](5)` work for ANY closure, not just ones this backend knows
how to wrap, so it is probably where this ends up even if it starts with the
first. Note that `kept[0]` on the compiled path is a BOXED read
(`_infer_return_maybe_kinds`'s marker, doc/MEMORY.html §7) — confirm whether
the box is also losing the `self` word before assuming the two are the same bug.

## Regression

`test_gimple_runner.py`'s `test_gimple_stdout`, appended to the
`gimple_nested_def_env_is_freed` program in that same file: `print(kept[0](5))`
must be `15`. That test already stores a nested `def` in a list; it does not
yet CALL the stored one, which is the entire gap.