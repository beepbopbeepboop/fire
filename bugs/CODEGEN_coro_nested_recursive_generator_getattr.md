# CODEGEN: coro.py's nested recursive generator with a dynamic getattr cannot compile

Found 2026-11-11 while landing the mixed-kind-name representation
(`bugs/CODEGEN_mixed_kind_names_need_a_representation.md`). It is the NEXT
blocker on `mojo/middle/coro.py` compiling, after the mixed container/scalar
parameter refusal was fixed.

## What I ran

```python
import os
from build_stdlib_dylib import compile_module_to_c
src = open("mojo/middle/coro.py").read()
compile_module_to_c(src, os.path.join(".tmp", "probe_coro.py"), "coro", linkable=False)
```

Expected: the C text (the module is part of the compiler's own import closure,
via `gimple_codegen.py`'s `import mojo.middle.coro as gimple_gen_coro`).

Actual:

    cannot compile module: function(s) _walk_lists (generator function(s), contain a
    `yield`/`yield from`) — ... Unsupported shape(s): _walk_lists: getattr(obj, name)
    with a non-static attribute name is not supported in a compiled generator/coroutine
    body (no runtime attribute-reflection table exists in this codegen)

`_walk_lists` is `mojo/middle/coro.py:5924`, defined inside
`_lower_callable_choices`'s nested `_rewrite_fn` (so two levels deep), and it
does `sub = getattr(st, fld, None)` for a field name that is only known at run
time.

## Minimal reproducer (independent of any mixed-kind name)

```python
def outer(body):
    def inner(fn):
        def walk(xs):
            for i, st in enumerate(list(xs)):
                yield xs, i
                for fld in ('body',):
                    sub = getattr(st, fld, None)
                    if isinstance(sub, list):
                        yield from walk(sub)
        return list(walk(fn))
    return inner(body)
def main():
    print(outer([1, 2]))
main()
```

This refuses with the same message on a tree with none of the mixed-kind-name
change. (The same program WITHOUT the `getattr` compiles to a C++ companion,
which `compile_to_gimple` cannot return but the real build can link — so the
`getattr` is the decisive part, not the nesting alone.)

## Why it happens

- `_lift_capture_free_nested_scopes` (`mojo/middle/coro.py:6347`) lifts a
  nested capture-free def only when that def is NOT itself a generator
  (`not getattr(h, 'is_generator', False)`), and only one level at a time. It
  lifts `_rewrite_fn`'s parent candidates, but `_rewrite_fn` captures
  `fn_names` from `_lower_callable_choices`, so it stays nested; `_walk_lists`
  is therefore never seen by the pass.
- The nested-scope machinery only reaches generators defined DIRECTLY in a
  top-level function or method, so `_walk_lists` falls through to the C++
  coroutine companion, whose expression emitter (`cpp_core.py:4292`) refuses a
  `getattr` with a non-static name.
- The ordinary (GIMPLE) codegen has a dynamic attribute dispatch
  (`_mojo_dispatch_getattr`) that an A3-lowered generator body would use, so
  the refusal is in the backend choice, not in the shape being unrepresentable.

## Exact next step

Pick one, in this order of preference:

1. Teach `_lift_capture_free_nested_scopes` to descend through a plain def it
   cannot lift (captureful or otherwise) and lift a capture-free grandchild
   generator directly to module level. The capture test must be against the
   whole enclosing scope chain, not just the immediate function. `_walk_lists`
   is the measured case. Then it is a module-level generator and the A3
   stack-switch lowering handles the dynamic `getattr` through the ordinary
   codegen.
2. If lifting a two-deep generator is not structurally safe, add the
   `_mojo_dispatch_getattr` call to `cpp_core.py`'s dynamic-`getattr` arm (the
   same helper the GIMPLE path emits) instead of refusing.

## Done when

`python3 -c "from build_stdlib_dylib import compile_module_to_c; \
compile_module_to_c(open('mojo/middle/coro.py').read(), '.tmp/coro.py', 'coro', linkable=False)"`
returns C text, and the fire.ci self-host build is green. Delete this doc in
the commit that closes it.

## Status

Open. Not started; filed from the mixed-kind-name round so the next session
does not have to re-derive it.
