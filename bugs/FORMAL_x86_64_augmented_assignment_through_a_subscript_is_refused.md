# FORMAL_x86_64_augmented_assignment_through_a_subscript_is_refused: `q[0] += 5` has no x86-64 lowering

**Area:** FORMAL (x86-64 codegen). **Found while** extending `os` with the
pointer-subscript route, which is arm64-only for this construct and so had to
be marked as such in `test_formal_os_backing.py`.

**Severity: an honest refusal, not a wrong answer.** The x86-64 backend says
`augmented assignment target must be a plain name on the formal x86-64 path
(got SubscriptExpr)` and stops. arm64 lowers the same source and gets the right
answer, so the two architectures disagree about whether a program works — which
is the shape this whole family of documents is about, and the one arm64-only
limitation in `os`'s own docstring is `dylib`-related rather than this.

## What I ran

```
$ cat > .tmp/aug.mojo
def main(n):
    var q: Pointer[Int32] = malloc(16)
    q[0] = 10
    q[0] += 5
    q[1] = 3
    q[1] *= 7
    printf("a=%d b=%d\n", q[0], q[1])
    return 0
$ python3 -c 'import sys; sys.path.insert(0,"."); import formal.build as B; \
    B.compile_formal(".tmp/aug.mojo", output=".tmp/aug", test_input=10, \
                     prove=False, arch="x86_64")'
FormalBuildError: augmented assignment target must be a plain name on the
formal x86-64 path (got SubscriptExpr)
$ # same source, arch="arm64"
$ ./.tmp/aug
a=15 b=21
```

Pinned by `test_formal_os_backing.py::pointer_subscript_augmented`, which is
marked `archs=["arm64"]` and says why in the runner's SKIP line.

## Why

`formal/x86_64_codegen.py:_emit_aug_assign` opens by deciding which name to load
and store, and the decision is:

```python
if isinstance(stmt.target, F.IdentExpr):
    name = stmt.target.name
elif isinstance(stmt.target, F.MemberExpr) and _member_slot_key(...) in (...):
    name = _member_slot_key(stmt.target)
else:
    raise CodegenError("augmented assignment target must be a plain name ...")
```

A `SubscriptExpr` target is none of those, so it refuses. arm64's
`_emit_subscript_aug` is a different shape: it computes the ADDRESS once with
`_emit_subscript_addr`, pushes it, reads the old element, applies the operator
and writes the new one back through the saved address — which is what a
read-modify-write through a computed address needs, and what the refusal above
is the absence of.

## What I expected

`q[0] += 5` to mean `q[0] = q[0] + 5`, the element read and written at the
pointee's width, on both architectures.

## The exact next step

In `_emit_aug_assign`, add a third arm for a `SubscriptExpr` target that
delegates, rather than a second implementation of the operator table. The two
pieces it needs are both already there on this backend:

1. `_emit_subscript_addr(target)` — which, after this branch's
   `model.subscript_base_lowering` change, also sets `self._sub_width` to the
   pointee's width, and answers for a list base, a string base and a declared
   pointer.
2. `_emit_subscript` / the `movzx` step, for the read at that width.

The shape is arm64's `_emit_subscript_aug` read through x86-64's slot discipline:
push the value, compute the address into a slot, reload the old element, apply
the operator, pop the address, store. The one thing to get right is the ORDER —
`_emit_subscript_store` already documents that the value must survive the
address computation, and `_emit_aug_assign` already spills the accumulator into
R11 for the same reason.

The operator table does not exist separately on x86-64 — `_emit_binop` picks
its encoder from the operator name in its own dispatch table, and
`_emit_aug_assign` reuses it for the plain-name case. Reusing that dispatch
rather than importing arm64's `ops` dict is the whole of "do not maintain two
implementations of the same operator list", and it is also what keeps the two
architectures agreeing about which operators a read-modify-write supports.
