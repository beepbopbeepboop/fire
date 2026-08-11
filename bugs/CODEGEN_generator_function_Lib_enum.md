# CODEGEN_generator_function: Lib/enum.py

## Status (updated 2026-08-10, re-verified + deepened — real fix attempted, concrete blocker found)

Re-confirmed against current master (fast-forwarded to `9d93746`,
which includes this session's tuple-valued-`yield` boxing work):
identical repro, identical 4 refusal lines, same fatal error. The
tuple-yield fix landed earlier this session (commit `a7b71a0`) does
NOT touch this file's failure at all — neither `_iter_member_by_value_`
nor `_iter_member_by_def_` yields a tuple.

**Real fix attempted and NOT landed — here is exactly what was tried
and why it stops short of safe:**

The classmethod/`cls` eligibility gate's own comment
(`gimple_codegen.py:26404-26407`) claims "no class-level attribute/
method access exists yet for compiled generators" as if this were a
totally unbuilt feature. That's not quite right — investigated the
actual machinery two levels deep:

1. **`cls.method(...)` calls already resolve correctly outside
   generators.** The ordinary (non-coroutine) `_lower_MemberExpr`/
   CallExpr path (`gimple_codegen.py:11822-11890`) already resolves
   `cls.method(...)` inside a real `@classmethod` purely by NAME (via
   `current_func_name` + `self._classmethod_names`, no runtime `cls`
   value needed at all) — this is a working, general mechanism, just
   never wired into the SEPARATE, hand-rolled coroutine-body emitter
   (`_cpp_expr`, `gimple_codegen.py:23816` on) that generator bodies use
   instead.
2. **`cls.<attr>` bare reads already have a redirect mechanism for
   `self`** — `self._class_attrs[struct_name][attr] -> global variable`
   (`gimple_codegen.py:9523-9530`, `29869-29910`), used today for
   `self.<class-attr>` reads. The exact same redirect, keyed off the
   enclosing struct name (derivable from `_cpp_gen_self_struct` the
   same way the eligibility check already derives `struct_name` for its
   scan), would trivially cover `cls._flag_mask_`/`cls._value2member_map_`
   in `_cpp_expr`'s MemberExpr case (`gimple_codegen.py:23882-23909`,
   which today ONLY handles `self.<field>`).

So a real fix for `_iter_member_by_value_`'s literal body (`for val in
_iter_bits_lsb(value & cls._flag_mask_): yield
cls._value2member_map_.get(val)`) looked tractable at first — `cls.
_flag_mask_` is a bare class-attr read (mirror the `self` redirect) and
`cls._value2member_map_` is too (`.get(val)` is then an ordinary dict
method call, already supported).

**Where it breaks: the YIELDED value's type would be silently wrong,
not just refused.** `cls._value2member_map_.get(val)` returns a `Flag *`
(an enum member reference), not a scalar. The yield-type inferencer
`_generator_yield_ctype` (`gimple_codegen.py:2758`) calls
`_infer_simple_expr_ctype` (`gimple_codegen.py:2472`) per yield site;
that function has NO case for a `CallExpr` whose `func` is an arbitrary
`MemberExpr` chain returning a struct pointer (its `CallExpr`-with-
`MemberExpr`-func branch, `gimple_codegen.py:2555-2580`, only
recognizes a small hardcoded allowlist — `os.path.*`, `math.*`, `str.
format`) — it falls through to `return None`, and
`_generator_yield_ctype`'s caller then does `t = None -> t =
'int64_t'  # default when type can't be inferred`
(`gimple_codegen.py:2841-2842`). That default is exactly wrong here: a
`Flag *` pointer would get silently reinterpreted/truncated as
`int64_t`, producing a wrong runtime value that still compiles clean —
a SILENT MISCOMPILE, strictly worse than today's honest refusal. Fixing
this properly needs `_infer_simple_expr_ctype` to recognize a dict
`.get()` call (and general struct-returning member-call chains) and
either (a) refuse (return `None` all the way through, i.e. make the
"can't infer -> default int64_t" fallback in `_generator_yield_ctype`
stop defaulting for this shape and refuse instead), or (b) actually
widen the coroutine promise/co_yield representation to carry a genuine
pointer value across the suspend boundary — the SAME kind of "value
crossing a suspend point isn't just a scalar" scope boundary already
tracked for tuple yields (now fixed) and for
`bugs/CODEGEN_generator_function_Lib_ftplib.md`'s `mlsd` case, just for
a bare struct-pointer yield instead of a tuple.

Given that landing (1)+(2) alone — without also closing the yield-type
gap in (3) — would trade an honest compile-time refusal for a silent
wrong-value bug, this fix was NOT applied. No code change made; no gate
run.

Independently, `_iter_member_by_def_`'s `yield from sorted(cls.
_iter_member_by_value_(value), key=lambda m: m._sort_order_)` would
ALSO still be refused even if all of the above were fixed — the
`key=lambda ...` argument hits the separate, already-documented
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` refusal
(a `LambdaExpr` used as a call argument inside a generator body). So
even a fully-correct fix for `_iter_member_by_value_` would not, by
itself, make `enum.py` build — `_iter_member_by_def_` needs that
separate, already out-of-scope gap closed too.

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
