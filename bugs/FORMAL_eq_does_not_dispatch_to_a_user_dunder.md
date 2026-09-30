# FORMAL_eq_does_not_dispatch_to_a_user_dunder: `a == b` never calls a class's own `__eq__`

**Status: OPEN, pre-existing, and not specific to `@dataclass`.** Measured
while proving the `dataclasses` transform: a class that declares `__eq__` has
that method reachable by an explicit call and NOT by `==`, on both
architectures. It is the reason `formal/dataclass_transform.py` refuses a
`@dataclass` that declares its own `__eq__` rather than accepting it and
silently computing an address comparison.

Found while writing the `dataclasses` transform for the formal backend
(2026-09-29, the `module:dataclasses` claim).

---

## What I ran

```python
class Plain:
    x: int
    y: int

    def __eq__(self, other):
        return True

def eq(a, b):
    if a == b: return 1
    return 0

def main(n):
    a = Plain(1, 2)
    b = Plain(3, 4)
    printf("eq-method=%d direct=%d", eq(a, b), 1 if a.__eq__(b) else 0)
    return 0
```

```console
$ python3 fire.py build --formal --no-prove -o owneq owneq.py && ./owneq
Built: owneq  [arm64/macho]
eq-method=0 direct=1
```

CPython prints `eq-method=1 direct=1`. So the method is FOUND and CALLED when
named explicitly, and the `==` operator bypasses it entirely.

## Why

`formal/arm64_codegen.py`'s `_emit_binop` maps `==` to one flag-setting compare
of two words (`_emit_cmp` / `_emit_cmp_flags`), with a separate branch for a
`char *` pair (`_emit_strcmp_flags`). There is no step that consults a method
table, because method dispatch on this path is BY NAME and only for the
`recv.m(x)` spelling — `formal/build.py`'s `_rewrite_method_calls` rewrites that
spelling into `S_m(recv, x)` from the method name alone, since `recv.m(x)`
carries no type. The operator spelling carries no method name at all, so
nothing reaches a method table.

That is the same structural fact `bugs/FORMAL_module_attribute_access_refused`
records from the other direction, and it is a real design limit rather than a
missing branch: making `==` dispatch would mean making the OPERATOR carry a
type, which is a type inference this path does not have.

## Why it matters here, specifically

CPython keeps a user-declared `__eq__` in preference to a dataclass's generated
one — measured, with `@dataclass class T` defining `__eq__`, `T(1) == T(2)` is
True where the generated one would say False. So a `@dataclass` that declares
`__eq__` is LEGAL and its meaning is unambiguous, and accepting it would build
an image that runs the comparison as an address compare and prints `0` where
the source's own method says `1`. Silently, from a program that did nothing
unusual. So it is refused, with the measurement in the message
(`own_eq_refusal`), and pinned by `test_dataclasses_formal.py`'s
`a_user_declared_eq_is_refused_not_silently_ignored`.

Note the asymmetry this exposes: the transform's own field-wise `==` rewrite is
the thing that makes the GENERATED `__eq__` correct, and it is only correct
because the comparison does NOT dispatch — it is a desugaring at the operator.
So the two halves of CPython's `__eq__` story land on opposite sides of this
limit, and only one of them can be right here. That is worth knowing before
anyone tries to close this.

## What would close it

**Route the operator through the method table when the receiver's type is
known.** The pieces exist and are already published: `_frame_receivers` computes
`fn._frame_candidates` (holder name → the structs it might be) and
`model.method_owner_names` maps a method to its struct, and
`formal/dataclass_transform.rewrite_equality` is a worked example of a
consumer of exactly that pair. So the shape is: at `==`/`!=`, if both operands
are holders whose agreed struct declares `__eq__`, rewrite the operator into a
call the way `_rewrite_method_calls` already does for `recv.m(x)`; if the
struct does NOT declare one, leave the operator alone (which is what makes
CPython's inherited `__eq__` correct, and is what `eq=False` relies on).

**Cost: small, and it is the same rewrite machinery the dataclasses transform
uses** — the new part is the agree-or-refuse over `fn._frame_candidates` and
the rule for "the struct does not declare `__eq__`, so do not rewrite", which
is the half that keeps it from changing every comparison in the tree. The
reversing question — a bare struct's `==` being an ADDRESS compare, which
CPython's identity `__eq__` also is, so it agrees today — must be pinned at the
same time or the fix silently changes it.

**Not in the `module:dataclasses` claim**: it is a codegen change in
`formal/arm64_codegen.py` and `formal/x86_64_codegen.py`, and it changes a
construct (`==`) that every file in the tree uses. It belongs to whoever owns
the operator lowering.
