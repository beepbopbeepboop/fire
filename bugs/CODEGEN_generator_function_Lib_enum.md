# CODEGEN_generator_function: Lib/enum.py

## Status (updated 2026-08-09, re-verified — consolidated)

**STILL FAILING**, re-confirmed against current master with
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/enum.py`
(this file as the build root):

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/enum.py
[gimple_codegen] generator method Flag.'_iter_member_by_value_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_value_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method Flag.'_iter_member_by_def_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_def_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method IntFlag.'_iter_member_by_value_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_value_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
[gimple_codegen] generator method IntFlag.'_iter_member_by_def_' not eligible for C++ coroutine path, falling back to honest refusal: _iter_member_by_def_: a @classmethod generator that references `cls` in its body is not supported (no class-level attribute/method access exists yet for compiled generators)
Error building: cannot compile module: function(s) _iter_member_by_def_, _iter_member_by_value_ (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Classification: expected, correct refusal — the classmethod/`cls`
generator eligibility gate (`bugs/hard/CODEGEN_generator_classmethod_
first_param_must_be_self.md`, task #147-adjacent, already fixed and
verified working as designed) doing its job.** `Flag._iter_member_by_
value_`/`_iter_member_by_def_` (enum.py lines 1428/1438) are
`@classmethod` generators whose bodies genuinely reference `cls`
(`cls._flag_mask_`, `cls._iter_member_by_value_(value)`,
`cls._value2member_map_.get(val)`) — this codegen has no class-level
attribute/method-access story for compiled generator coroutines, so the
eligibility check correctly refuses rather than emit invalid C++
(member access on a scalar `int64_t cls` placeholder). `IntFlag`
inherits both methods unchanged from `Flag` (`class IntFlag(int,
ReprEnum, Flag, ...)`, no override) — the codegen flattens inherited
methods per concrete struct, so `IntFlag` gets its own independently-
refused copy of each, which is why 4 refusal lines appear for what is
really 2 distinct method BODIES.

`_iter_member_by_def_`'s `yield from sorted(cls._iter_member_by_value_
(value), key=lambda m: m._sort_order_)` is ALSO independently refusable
on `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s grounds
(a `LambdaExpr` used as a call argument inside a generator body) — a
second, independent reason this exact generator would be refused even
if class-level `cls` access were supported. Not cross-verified which
check fires first in the current eligibility-scan order; moot, since
both are out-of-scope structural gaps.

Not fixed here — both are documented, already-assessed, feature-sized
coroutine-codegen scope boundaries (class-level attribute/method access
from a compiled generator; lambda-as-call-argument inside a generator
body), not narrow bugs, and per this session's scope neither is to be
attempted.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/enum.py
