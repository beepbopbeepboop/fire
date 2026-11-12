# CODEGEN: coro.py's nested recursive generator with a dynamic getattr cannot compile

Found 2026-11-11 while landing the mixed-kind-name box representation (the
float-and-str-in-one-name fix; the bug doc that recorded it has been deleted
now that its named cases pass). It is the NEXT blocker on
`mojo/middle/coro.py` compiling, after the mixed container/scalar
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

## Status (2026-11-12)

- `mojo/middle/coro.py` now COMPILES to C. It no longer contains the shape
  this doc is about: `_lower_callable_choices`'s `_walk_lists` is an eager
  list-returning recursive function instead of a recursive generator, so its
  dynamic `getattr` goes through the ordinary codegen. The module's own
  compile is pinned by `test_selfhost.py::coro_module_compiles_to_c` (fails
  before that rewrite with this doc's refusal, passes after). The fire.ci
  self-host build itself was NOT run (the integrator runs the gate).
- STILL OPEN for the SHAPE, not for coro.py. The minimal reproducer in this
  doc still refuses. Option 1 (lift the capture-free deep generator) was
  implemented and measured far enough to find the two NEXT obstacles, so a
  later session does not have to rediscover them:
  1. Once lifted to module level, `yield from self(...)` is read by
     `_generator_value_kind` as an unresolved delegation: `_resolve_gen_kind`
     breaks the self-cycle by returning None, and `_generator_value_kind`
     counts that None as a NON-TUPLE yield beside the direct tuple yield, so
     the generator is refused with "mixed tuple / non-tuple yields (v0)".
     The honest fixpoint is to treat `yield from <this same generator>` as
     contributing no new kind (the direct yields answer it).
  2. After that, the tuple-slot static typing refuses: `_walk_lists`'s
     `yield body, i` has slot `body` whose call sites (`fd.body`, and the
     recursive `sub` from `getattr`) the static scan cannot type, so
     `_ambiguous_yielded_params` returns `{'body'}` and the A3 slot has no
     fixed C type. A codegen fix needs a boxed/tagged tuple slot (the
     `'l'` box kind exists in `mojo_repr_boxed`) or a static type the scan
     can actually prove. Rewriting the call sites to avoid an untyped
     parameter would defeat the point: user code of this shape stays
     untypeable by construction.

### Update 2026-11-12 (round: obstacle 1 landed)

- LANDED: obstacle 1 above. `_generator_value_kind` now treats
  `yield from <this same generator>` as contributing no kind
  (`_is_self_delegation`, mojo/middle/coro.py). A module-level recursive tuple
  walk resolves to `('tuple', '')` instead of
  `(None, 'mixed tuple / non-tuple yields (v0)')`. Pinned by
  `test_gimple.py::test_self_delegating_generator_kind_ignores_its_own_yield_from`
  (fails on the pre-fix kind answer, passes after).
- NOT CHANGED: the minimal reproducer above still refuses, now at obstacle 2
  (the tuple-slot static typing: `body` is untyped, `_ambiguous_yielded_params`
  returns `{'body'}`). Done-when is therefore still unmet; this doc stays open.
- Next step: obstacle 2. Decide between a boxed/tagged tuple slot for
  parameters the static scan cannot type (the `'l'` box kind in
  `mojo_repr_boxed`) and a scan that proves `body`'s kind from the call sites
  (`fd.body`, and the recursive `sub` from `getattr`).
- Not verified this round: the fire.ci self-host build (integrator gate).
