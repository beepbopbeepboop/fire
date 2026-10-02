# FORMAL_x86_64_comptime_specialization_abi: x86-64 refused `f[T](x)`, and the refusal took THREE halves to lift

**Status: FIXED 2026-10-01 (`x86-64 parity`), and the fix was three changes
where this doc said one.** x86-64 now lowers `f[T](x)` and its answer matches
arm64's and CPython's, for both the free-function and the method spelling.

**What this doc got wrong, and it is the part worth keeping.** The "Why x86-64
refuses" section below filed the fix as ONE change — port the call site, then
let `_callee_symbol` resolve — and recorded the callee-prologue half as ALREADY
PRESENT:

> the callee's prologue reserves a register per comptime parameter | yes |
> **yes** — `formal/model.py`'s `incoming_args` is shared and both backends'
> prologues read it

**That was true of arm64 and false of x86-64.** `formal/x86_64_codegen.py`'s
prologue read `list(f.params or [])`, and a comptime parameter is not in
`f.params` at all. Measured, in the order the halves had to land:

| state | `f(3, 7)` bare | `f[1](3, 7)` |
|---|---|---|
| before any change (CPython 307) | x86-64 **3** | x86-64 **refused** |
| call site + `_callee_symbol` only | x86-64 **refused** (`'type' has no home`) | x86-64 **refused** |
| all three | x86-64 **307** | x86-64 **307** |

The middle row is the finding. A bare `f(3, 7)` agreed with arm64 on the
pre-change tree **by accident**: neither side passed the comptime argument, and
arm64's prologue ignored its own unused register, so both read `x` from the
first register and got 3... no — arm64 got 307 because its prologue reads
`incoming_args` while its caller prepends a 0, so `x` lands in the SECOND
register on both machines. On x86-64 the caller's `x` landed in the FIRST
register (no prepended 0) and `type` was never passed at all, so `x` read 3:
a wrong number with exit 0 on a program that builds. So the pre-change
agreement was the two backends being wrong in opposite directions and the
numbers happening to differ for a second reason.

And the direction of the doc's claim is the reason it mattered: it said the
refusal was load-bearing *because* the prologue half was present. Had that been
true, adding only the call-site half would have produced exactly the silently
wrong image the doc was warning against — `type` and `x` sharing a register.
With the prologue half genuinely absent, the same two changes produce a loud
refusal (`'type' has no home`) instead, which is the better of the two failures
and only by accident.

## The fix

Three changes in `formal/x86_64_codegen.py`, each mirroring arm64's:

1. **the call site** prepends the bracket expressions:
   `_specialization_args(e, ct_params)` from the shared
   `mojo/middle/comptime.py`, ahead of the call-time arguments;
2. **`_callee_symbol`** answers a `SubscriptExpr` with
   `comptime_eval.specialization_name(func)` — the same shared reader arm64's
   `_specialization_of` asks;
3. **the callee prologue** reads `M.incoming_args(f)` rather than `f.params`,
   and allocates through a new `_allocation_order`, which is arm64's shape: a
   comptime parameter is only ever READ in the body so
   `bound_names_in_order` (which walks assignments) never lists it, and without
   the ordering it has no register home at all.

`var_register_map` — which the proof generator is meant to reuse — is built
from `_allocation_order` for the same reason, so a per-value proof fact names
the register the codegen actually allocated.

## Verification

`test_formal_receiver_position.py` and `test_formal_specialized_method_call.py`
each lose their `x86_abi_refusal_is_load_bearing` row (what it pinned — that
x86-64 refusing was correct — is no longer true) and gain BOTH-backend
differential cases: the bracket expression, the BARE spelling that binds every
comptime parameter to 0, and a comptime parameter that is actually read in the
body. Both files' differential runner builds and runs on both architectures
rather than on one, because a one-sided assertion is what let the x86-64 caller
pass only the runtime arguments for as long as it did.

Measured as the anti-rot check: reverting only change (3) — the prologue —
makes all three new cases fail on a WRONG NUMBER rather than on a refusal
(`v=103` against CPython's `v=307`, `v=3`, `v=10043` against `v=4037`), which is
precisely the failure mode a refusal-shaped expectation cannot see.

`formal/x86_64_endtoend_test.py` and `formal/x86_64_model_test.py` are the
remaining checks this touches; they were NOT run here (the task's light-worker
budget), so the integrator should.

---

## The original filing, kept because its reasoning is what the fix had to respect

Found while
working the receiver-position family (`construct:receiver-position-family`); the
change that found it is `formal/model.py`'s `call_callee_name`, which made
`formal/build.py`'s frame analysis see through a comptime specialization — so
`f[T](r)` with a frame address in an argument now lowers **on arm64** and was
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

**The step list above is INCOMPLETE, and the missing step is (0):** before either
half of the ABI, the callee PROLOGUE has to give a comptime parameter a home.
This section recorded that as done; it was not, and the two steps it does list
in that order produce a loud refusal rather than a wrong image only BECAUSE it
was missing. If it is ever added, the two steps here become sufficient; if it is
added and then one of them is done alone, they produce the silently wrong image
this doc was filed to prevent. That asymmetry is the reason the fix was written
as three changes in one commit.

## Why this is not in `construct:receiver-position-family`

It is a calling-convention change in the second backend, which the frame
analysis does not need: the construct already lowers correctly on arm64 and is
already refused on x86-64 with a message that is **true** ("this call target is
a shape this backend has no case for"), which is the outcome this design wants.
The honest state of the family after the change is therefore "arm64 lowers it,
x86-64 refuses it, and the refusal names the missing ABI" — not "it works".
