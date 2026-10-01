# FORMAL_x86_64_comptime_specialization_abi: x86-64 refuses `f[T](x)`, and the refusal is load-bearing

**Status: OPEN, and the refusal must stay until the ABI is ported.** Found while
working the receiver-position family (`construct:receiver-position-family`); the
change that found it is `formal/model.py`'s `call_callee_name`, which made
`formal/build.py`'s frame analysis see through a comptime specialization — so
`f[T](r)` with a frame address in an argument now lowers **on arm64** and is
refused **on x86-64** by the emitter. The two answers differ and the difference
is the finding.

## What was measured

```
$ cat f.mojo
def f[type: Int](x: Int, y: Int) -> Int:
    return x * 100 + y

def main(n: Int) -> Int:
    return f[1](3, 7)

$ python3 fire.py build --formal --no-prove --backend=arm64   f.mojo -o f.arm64
Built: f.arm64  [arm64/macho]            # exit 307   (307 & 0xFF = 51)
$ python3 fire.py build --formal --no-prove --backend=x86_64 f.mojo -o f.x86
build: unsupported call target on the formal x86-64 path (got SubscriptExpr)
```

307 is `3*100 + 7` with `type`=1 bound separately, which is the receipt that the
arm64 half puts the comptime arguments ahead of the call-time ones.

## Why x86-64 refuses, and why it must not simply be told the callee's name

The two backends do not share the comptime ABI, and only ONE of the three halves
is present on x86-64:

| half | arm64 | x86-64 |
|---|---|---|
| the callee's prologue reserves a register per comptime parameter | yes | **yes** — `formal/model.py`'s `incoming_args` is shared and both backends' prologues read it |
| the call site passes the bracket expressions AHEAD of the call-time arguments | yes — `_emit_call`'s `_specialization_args` | **no** — no such code in `formal/x86_64_codegen.py`, and its own constructor docstring says "this backend has no specialization pass yet" |
| `_callee_symbol` resolves a `SubscriptExpr` callee to the bare name | yes — `_specialization_of` → `comptime_eval.specialization_name` | **no** — returns `None` |

The third row is what makes the program refuse today, and it is a **lucky**
refusal: it is standing in for the missing second row. Making it resolve the
name alone would produce exactly the wrong image. With `type` in R13, `x` in R14
and `y` in R15 (row 1) and a caller that puts `3` in RDI and `7` in RSI (row 2
absent), `x` would read 7 and `y` would read whatever was in RSI before — a
wrong number with exit 0, which is the outcome this backend exists to make
impossible.

So the fix is **not** in the analysis and **not** a one-line delegation of
`_callee_symbol`; it is to port the call-site half:

1. in `formal/x86_64_codegen.py`'s `_emit_call`, after `bind_call_arguments`,
   prepend `comptime_eval.specialization_args(e, ct_params)` when
   `M`/`comptime_eval`'s `param_names(self._functions[name])` is non-empty —
   the same three lines arm64 has, and `mojo/middle/comptime.py` is already
   shared, so the RULE is not re-implemented;
2. only then let `_callee_symbol` answer a `SubscriptExpr` — and it should do
   so by calling `formal/model.py`'s `call_callee_name`, which is the
   analysis's own recogniser, so the analysis and the emitter cannot come apart
   (that is the same reason `incoming_args` is shared).

Step 1 alone is enough to make `f[1](3, 7)` correct on x86-64 and the
specialization is then usable from the frame analysis on both architectures.

**Verification when it lands:** the six differential cases and the two guards in
`test_formal_receiver_position.py` move from `COMPTIME_ABI = "arm64"` to
`BACKENDS`, `X86_ABI_REFUSALS` is deleted, and `formal/x86_64_endtoend_test.py`
plus `formal/x86_64_model_test.py` (43 agreements on the baseline) stay green.

## Why this is not in `construct:receiver-position-family`

It is a calling-convention change in the second backend, which the frame
analysis does not need: the construct already lowers correctly on arm64 and is
already refused on x86-64 with a message that is **true** ("this call target is
a shape this backend has no case for"), which is the outcome this design wants.
The honest state of the family after the change is therefore "arm64 lowers it,
x86-64 refuses it, and the refusal names the missing ABI" — not "it works".
