# INTERP: a `List`/`Dict` field with no initializer is `None`, where Mojo (and the compiled path) make an empty container

**Area:** INTERP (`myinterpreter.py`). **Status: OPEN, measured 2026-10-07.**
Found while fixing the scalar half of the same question (a `var x: Int` field
with no initializer read as `None` instead of `0` — that fix landed and its doc
is deleted). The scalar case is fixed for `Int`/`Float*`/`Bool`; the CONTAINER
case is not, and it is the remaining half.

## What I ran

```
$ printf 'struct Box:\n    var s: String\n    var xs: List[Int]\n\ndef main():\n    var q = Box()\n    print(q.s)\n    print(q.xs)\n' > .tmp/strbox.mojo
$ python3 fire.py run .tmp/strbox.mojo
None
None
$ python3 fire.py --jit .tmp/strbox.mojo
None
[]
```

The `List[Int]` field is `[]` on the compiled path (Mojo's empty container) and
`None` on the interpreter. `q.xs.append(1)` on the interpreter is therefore a
`NoneType` attribute error, where the language and the compiled path accept it.

The `String` field is `None` on BOTH engines, so it is a shared (not a
divergence) gap and is deliberately not part of this doc.

## Why it is not `0`

The scalar fix (in `_coerce_to_declared_type`) maps `None` to the declared
scalar's zero. A container must NOT go through that: `0` is not a `MojoList *`,
and forcing one is the plausible-wrong-answer class the scalar fix's own doc
warned about. The empty container is a different default, produced by the
container's constructor (`List[Int]()`), not by a numeric zero.

## The exact next step

`MojoClass.__call__`'s field loop (beside the existing `_array_field_default`
branch) needs a container arm: when `f.value is None` and `type_ann` names a
`List`/`Dict`/`Set` (including the `List[T]` subscript spelling the parser
records), bind a fresh empty container of that kind instead of leaving `None`.
`_MojoGenericCtor`/the interpreter's builtin `list`/`dict`/`set` constructors
are the vocabulary for the empty value. Keep it scoped to the containers the
interpreter actually models; an annotation it cannot map must stay untouched,
the same conservative rule the scalar fix follows. The cheapest measurement is
the three-line probe above through `fire.py run` vs `fire.py --jit`.
