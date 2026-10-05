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
## Status, 2026-10-05 (`formal29-2-r2`): the load is still refused, and the
## PREREQUISITE this list did not know about now exists

Nothing in "What has to change to let it through" has landed, and item 1 is
still the first step. What has landed is a piece of item 3's machinery, plus the
finding that makes it a prerequisite rather than a convenience — **so read this
before starting, because the order in the list above is not the safe order.**

### The hazard: allowing the load without a kind creates a NEW wrong answer

Both backends place a `printf` vararg from the FORMAT, not from the operand's
kind, so with the `Float64` row of `POINTEES_REFUSED` deleted and no kind
flowing, `printf("%d", p.value())` would compile and print the double's bit
pattern as a decimal — the defect measured and fixed in
`bugs/FORMAL_float_binary64_only.md`'s last section, in the same shape
`printf("[%d]", x)` had for a named `Float64` parameter (`[858993459]` for 3.9).
The refusal here is the only thing standing between a wrong answer and that
source today, which is why the two changes have to land together and not
either-or.

### What exists now: the operand-kind reader both emitters ask

`model.printf_arg_float_evidence(expr, vk, is_float)` is the reader item 3 asks
for — "the operand-kind reader has to see through the dereference" — with the
evidence discipline already written: a `FLOAT_KIND` operand is positive evidence
from the emitter's own `_expr_str_kind`, an integer is positive evidence from
`ValueKinds.own_shape_kind`, and **None never refuses**, because both backends
place from the format and an unclassified operand is correct there.

**Its hook is where the pointee's kind goes.** `is_float` is the one thing it
cannot derive, and the natural content for it is a `pointer_pointee`-backed
answer — `pointer_pointee(fn, expr, decls, functions)` already resolves the
declared pointee of a name, a `recv.field`, a pointer construction and a
`bitcast`, and `Float64` is a key of `POINTEES_REFUSED` already, so the reader
that classifies a dereference exists in every respect but the one question. That
is item 1's channel, and it wants to be a `ValueKinds` hook beside
`declared_kind`/`param_kind` so `_expr_str_kind` inherits it rather than each
emitter re-deriving it.

### The remaining work, with the two consumers that are NOT covered

Good news first: both backends' float-to-int conversion arms already expect the
operand's bits in a GENERAL-PURPOSE register and do the register-file crossing
themselves — arm64 `encode_fmov_gpr_to_v` + `encode_fcvtzs_xn_dn`, x86-64
`encode_movq_xmm_rm64` + `encode_cvttsd2si_r64_xmm` — which is exactly where an
`LDR`/`mov` of eight bytes leaves them. So item 2 (`Int(p.value())` becomes
`FCVTZS`) needs the kind hook and nothing else, and item 3's `printf("%f", …)`
case needs the kind hook and nothing else, because the placement is already the
format's.

Two consumers are NOT covered by that, and they are the reason this is still a
project rather than the two-line change it looks like from here:

  1. **an argument in WORD position.** `g(p.value())` for `def g(x: Int)` puts
     a double's bits into a parameter the source declared an integer. There is no
     float-mismatch rule for call arguments; `float_binary_refusal` is about
     operators, and the kind flow does not reach `g`'s parameter list.
  2. **a `return` under an integer annotation.** `def f(p: Pointer[Float64]) ->
     Int: return p.value()` — the declared return type is what a caller asks
     about (`func_kind`), so the callee looks like it produces an integer and
     every consumer of the result is right to believe it.

Each of those is a silent wrong answer rather than a refusal, so the load cannot
go through until both are refused by name. That is the exact next step, and it
is one shape at a time: a call-argument class check beside
`printf_kind_conversion_refusal` (the same rule, the same evidence, one more
place the format's analogue does not exist), then the return annotation.
