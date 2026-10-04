# A `Pointer[Float64]` load is bit-exact and is still refused, because the KIND is decided by the context

**Area:** FORMAL (the pointer value model). Claim `project26:float`, found
2026-10-04 on `work/formal26-float` while correcting a refusal reason that the
binary64 work had made false. **NOT FIXED** — and it is NOT the binary32 case, which
is a real absence of a kind; this is the opposite, and the distinction is the whole
of this doc.

## What was run

```
$ cat p64.mojo
def read_f(p: Pointer[Float64]) -> Int:
    return Int(p.value())
def main(n: Int) -> Int:
    var s = "ABCDEFGH"
    return read_f(s)

$ python3 fire.py build --formal --no-prove --backend=arm64 -o p64 p64.mojo
build: p.value() is a load from the address the receiver holds, and the load's
width is the pointee's — the pointee is Float64, and a Float64 is eight bytes of
IEEE binary64 and the LOAD is bit-exact — one word holding the bit pattern — but
this dereference path yields a word whose KIND is decided by the context it lands
in, and a context that has established none answers `int`, so `Int(p.value())`
would read the exponent field; see bugs/FORMAL_float_pointer_pointee.md.
```

And the `Float32` sibling, which is refused for a DIFFERENT and still-true reason:

```
build: … the pointee is Float32, and a Float32 is four bytes of IEEE binary32 and
this path has no float kind distinct from an int, so the load would put float bits
in a register the program then treats as an integer — a wrong answer, not an
approximation.
```

## Why the two are different, and why the distinction is worth a document

`formal/model.py`'s `POINTEES_REFUSED` refused `Float64` for the same words as
`Float32` until 2026-10-04, and those words were **half true**. They were true of
`binary32`, whose four bytes are not a double's eight, and they were FALSE of
`binary64` the moment `FLOAT_KIND` landed: a `Pointer[Float64]` load is an `LDR` of
eight bytes holding the bit pattern, which is bit-exact, and nothing about it needs
a kind.

So `Float64` is refused for a reason about the CALL SITE rather than the value:
`p.value()` yields a WORD, and whether that word is an integer or a double is
decided by whatever it lands in — `Int(...)`, a comparison, a `%d` format — and a
context that has established none answers `int`, which reads the exponent field.
`Float32` has no such subtlety available to it: there is no kind for it to be, at
all, in either place.

`test_formal_run.py` has a row for each, with a needle naming its own reason, and
that split is what makes the two rows worth having rather than one row twice.

## What has to change to let it through

1. **`pointer_pointee` / `dereference_lowering` have to carry a KIND, not a width.**
   Today the dereference path answers "how many bytes" and the CONTEXT answers
   "what is it", which is why the two halves cannot meet for a double: there is
   no channel from one to the other. The `ValueKinds` hook that already exists
   (`declared_kind`, `param_kind`, `ctor_field_value`) is the pattern — a pointer
   expression needs a hook that answers its pointee's kind, and the emission has to
   convert rather than move.
2. **`Int(p.value())` over a `Float64` then becomes `FCVTZS`** and not a bit move,
   which is `IEEE754.ToIntBits` — the specification this library already states
   (`lib/IEEE754.lean`'s `ToIntBits`, a `Prop` because this toolchain's `Float` API
   has `Float.toUInt64` and no `Int` conversion).
3. **`printf("%f", p.value())`** needs the SSE placement x86-64 already has for a
   named double (`encode_movq_xmm_rm64` in the extern-call register plan) to fire
   on a pointer expression, which means the operand-kind reader has to see through
   the dereference.
4. **The Lean side is already ready**: `IEEE754`'s functions take a `UInt64` and
   return a `UInt64`, which is exactly what an `LDR` produces and what `FCVTZS`'s
   step will consume. That is why the semantics landed first.

## The tempting shortcut, and why it is wrong

Making the load unconditional — emit the `LDR` and let the context sort it out —
produces a green build that prints a double's exponent field as a decimal for
every program that does `printf("%d", *p)`, which is the failure mode
`formal/model.py`'s pointer-refusal docs are three paragraphs long about. A
refusal whose reason is "the context has not established a kind" is the honest
answer at the boundary, and the work is to widen what the context can establish.