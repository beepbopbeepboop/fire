# CODEGEN_generator_function: Lib/enum.py

## Status (updated 2026-08-20 — struct-pointer-yield gap CLOSED; enum.py's OWN refusal unchanged)

The 2026-08-10 note below (option (b): "actually widen the coroutine
promise/co_yield representation to carry a genuine pointer value across
the suspend boundary") is now implemented, as a real, general feature —
not narrowly overfit to `cls._value2member_map_.get(val)`'s exact shape.
Verified independently of enum.py itself (see "enum.py's own status,
re-verified" below for why enum.py's build error is unchanged despite
this).

**What was fixed.** `_infer_simple_expr_ctype` (`gimple_codegen.py`,
~line 2718) — the function `_generator_yield_ctype` calls per yield site,
whose `None` result used to silently default to `int64_t` — now
recognizes three real-struct-pointer-producing shapes, gated behind three
new optional parameters (`known_structs`, `dict_val_types`,
`method_return_types`; every existing caller that doesn't pass them keeps
the original scalar-only behavior unchanged):
1. `self.<field>` where the field's own declared type is a known struct
   pointer (was previously excluded outright — only the four scalar
   ctypes were accepted).
2. `<dict-typed self.field>.get(key)` — the exact enum.py shape,
   generalized to any `dict[K, StructType]`-typed field, not just
   `_value2member_map_`. Resolved via `self._field_dict_val_types`, the
   SAME per-struct-field dict-value-type registry the ordinary (non-
   generator) GIMPLE path already populates from a `.get()`/`d[k]` read —
   reused, not reinvented — but that registry is normally populated
   LAZILY (during ordinary per-statement body compilation), which runs
   AFTER generator methods are translated (gen_module's "Milestone C step
   3" pass) — so it was empty at the time a generator method needed it.
   Fixed by ALSO seeding it eagerly, from the field's own `var x: dict[K,
   V]` class-body declaration, at the SAME early struct-field-type
   pre-pass that already resolves a field's plain ctype this early (the
   struct-pointer-typed-parameter case reads `self.struct_field_types`
   this same early, confirming the pre-pass's timing was already right
   for this) — one extra `self._annotation_dict_val_type(field.type_ann)`
   call reusing the existing helper, not a new type-annotation parser.
3. The general case: an arbitrary `<receiver>.<method>(...)` call chain
   where `<receiver>` recursively resolves to a known struct pointer —
   resolved via `method_return_types` (`self.func_return_types`, the SAME
   registry every ordinary compiled struct-method CALL site already uses,
   keyed `f"{struct_name}_{method_name}"`).

**Promise/co_yield representation — confirmed unchanged, as expected.**
Verified BEFORE writing any fix (a minimal `yield <struct-pointer-typed
param>` repro) that a bare struct-pointer yield already compiled and ran
correctly end-to-end with ZERO promise/co_yield/consumer-side code
changes — `_c_to_cpp_scalar_type` already passes a struct-pointer ctype
straight through unchanged (same as the pre-existing `char *`/`MojoList
*` cases), the coroutine promise's `current_value` field/`yield_value`
parameter/`{base}_value` return type already work for ANY ctype
generically, and the ordinary `for x in gen():` consumer-side unboxing
(`_cpp_for_stmt`'s non-tuple branch) already declares the loop target
with whatever `vct` it's given, with no hardcoded scalar/MojoList*
allowlist. So this really was the "materially simpler" feature the task
anticipated — no promise-shape change of any kind was needed, confirming
option (b) from the 2026-08-10 note.

**Two real gaps DID need closing beyond pure type inference**, both
found by actually compiling+linking+running an end-to-end repro (not
just a `-fsyntax-only` .cpp compile):
- `_cpp_expr`'s CallExpr/MemberExpr lowering had NO case for `<dict>.get(
  key)` at all — it fell through to the generic `{obj}.{member}(args)`
  C++ text, which doesn't compile against an opaque `MojoDict *` (no real
  C++ member functions). Added a case mirroring the existing
  `mojo_dict_get_int`/`_double`/`_str` three-way dispatch the ordinary
  (non-generator) path's own `.get()`/`d[k]` lowering already uses,
  casting the `mojo_dict_get_int` result back to the real struct pointer
  type when the dict's value type is one (pointers are stored as int64_t
  in this dict representation — same convention `_pack_kwargs_dict`'s own
  docstring documents for "ints, doubles, pointers").
- The .cpp preamble's struct-typedef emission only pulled in a struct
  reachable via `self`, a generator/async parameter, an inline
  constructor call, or (transitively) one of THOSE structs' own fields —
  never a struct reachable ONLY through the yielded value's resolved
  type. Added `self._cpp_value_struct_names`, populated wherever a
  generator/async unit's finalized `value_ctype` is a struct pointer,
  merged into the same typedef-emission BFS the other three sources
  already feed.

**Verification.** Two new isolated repros in `test_gimple_generator_
runner.py` (real compile+link+RUN, asserting on actual stdout, not just
"compiles"): `struct_ptr_dict_get_yield` (the `self.<dict-field>.get(k)`
shape) and `struct_ptr_method_chain_yield` (the general method-call-chain
shape: `o.get_inner()` returning another struct pointer, yielded
directly). `struct_ptr_bare_param_yield` added too as an explicit
regression guard for the already-working bare-struct-pointer-yield case.
All pass; all 36 pre-existing generator-runner tests still pass (39
total); `test_gimple.py` (248/248), `test_module_cache.py` (76/76),
`make check-selfhost` all green; a from-scratch stdlib dylib rebuild
shows 0 `skip <module>:` lines both before and after this change (no
regression — expected, since this fix doesn't by itself unblock any
currently-refused stdlib generator: enum.py's own two generator methods
are refused by the SEPARATE cls-access gate below, before this fix's
code path is ever reached, and no other stdlib generator this session's
corpus scan found was gated on struct-pointer-yield type inference
alone).

**enum.py's own status, re-verified — UNCHANGED, as expected.**
`MOJO_DEBUG=1 python3 mojo.py build .../Lib/enum.py` still produces the
exact same 4 refusal lines it did before this fix, verbatim: `Flag`/
`IntFlag`'s `_iter_member_by_value_`/`_iter_member_by_def_` are still
refused for "a @classmethod generator that references `cls` in its body
is not supported". That gate (`bugs/hard/CODEGEN_generator_classmethod_
first_param_must_be_self.md`) fires at generator-ELIGIBILITY time, before
the body is ever translated — so it refuses `cls._value2member_map_.
get(val)` for referencing `cls` at all, never even reaching this fix's
new `_infer_simple_expr_ctype` logic (which only runs on a body that
passed eligibility). This fix closes the SEPARATE, real gap the
2026-08-10 note below root-caused (what happens to the YIELD TYPE once
`cls`-attribute access is eventually supported) — it does not, and was
never going to, touch the `cls`-access gate itself; that remains exactly
as out-of-scope as the 2026-08-09 note below already assessed it to be.
`_iter_member_by_def_`'s independent `LambdaExpr`-as-call-argument
refusal (`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`) is
likewise unaffected. So: the specific silent-miscompile risk this
session's earlier real-fix-attempt correctly declined to ship (landing
`cls`-access without ALSO closing the yield-type gap) is now closed, but
enum.py itself needs the `cls`-access gap fixed FIRST before this fix
can even become visible on that file — still not attempted, still
feature-sized, still out of this fix's scope.

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
