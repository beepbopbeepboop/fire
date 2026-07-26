# CODEGEN: compiled generator with an UNANNOTATED string parameter silently mistyped as int64_t

## Discovery context

Found via independent verification of Milestone C step 1 of the
compiled-path generator codegen project (commit `292f853`, "compiled
generator parameters via C++20 coroutines"). That commit's own test suite
correctly refuses an EXPLICITLY-annotated non-scalar parameter:

```python
def f(s: String):
    yield 1
```
(`test_gimple.py`'s `generator_string_param_honest_fallback`) — this
correctly raises the honest-refusal `RuntimeError`.

But an UNANNOTATED parameter that is actually a string at its call site
slips through uncaught:

```python
def g(s):
    yield s
print(list(g("hi")))
```

- `python3 mojo.py run repro.py` (interpreter): correct, prints `['hi']`.
- `python3 mojo.py build repro.py -o out && ./out`: compiles with NO
  refusal and NO error, producing a binary that also prints `['hi']` —
  but only by accident.

## Root cause

Confirmed directly via `gimple_codegen.compile_to_gimple_with_cpp`: the
generated `.cpp` for `g` types the parameter (and the coroutine's
`current_value` field) as `int64_t`:

```cpp
struct _mojogen_g_promise {
    int64_t current_value{};
    ...
    std::suspend_always yield_value(int64_t v) { current_value = v; return {}; }
    ...
};
static _mojogen_g_Task _mojogen_g_impl (int64_t s) {
    co_yield s;
    co_return;
}
```

The parameter-type refusal logic added in `292f853` only checks EXPLICIT
type annotations to decide a parameter is non-scalar and refuse. An
UNANNOTATED parameter has no such signal, so whatever inference this
codegen path uses for unannotated generator parameters evidently defaults
straight to `int64_t` with no cross-call-site type inference at all —
unlike the sophisticated mechanism this session already built and proved
out for the EXACT same class of problem in the ordinary (non-generator)
compiled-function path: the "cross-call scalar contract" fixed in commits
`e387af9`/`8799ec4`/`06ebde1` (see those commits — `_infer_param_types`,
the Pass 1.3d/1.3e/1.3f re-inference passes in `gimple_codegen.py`), which
observes call-site argument types (including string literals) to correctly
infer an unannotated parameter's real type instead of defaulting to
`int64_t`.

The repro above "works" only by luck: a `char*`/`MojoStr*` pointer value,
stored into an `int64_t`-typed slot and later read back out unchanged (never
arithmetically touched, never compared, never concatenated), survives the
round-trip bit-for-bit on this platform/ABI. This is NOT a supported
feature — it's a silent type-safety violation that would break as soon as
the yielded value were used for anything that depends on its real type
(string operations inside the generator body, a generator yielding
different types across iterations, certain compiler optimizations that
assume `int64_t` semantics for that slot, etc.).

## Impact

Any unannotated generator parameter that's actually a non-scalar type at
its call site(s) is silently miscompiled rather than honestly refused —
exactly the "silently wrong or broken code" outcome this whole project's
honest-refusal design has been careful to avoid everywhere else.

## Suggested fix

Either:
1. **(Safer, simpler, recommended for now)** Tighten the refusal check so
   an UNANNOTATED generator parameter is refused unless it can be
   POSITIVELY confirmed scalar — e.g. reuse the existing cross-call-site
   scalar-contract inference (`e387af9`'s mechanism) to check whether every
   call site passes a scalar (`int64_t`/`double`/`_Bool`) argument, and
   refuse (fall back to interpretation) if that inference is inconclusive,
   ambiguous, or finds a non-scalar argument anywhere — rather than
   defaulting to `int64_t` when uncertain. This matches this project's
   established "when in doubt, refuse honestly" philosophy exactly.
2. **(More capable, more work)** Actually reuse/extend the cross-call
   scalar-contract mechanism itself for the generator parameter path, so
   an unannotated parameter genuinely used only as a scalar across every
   call site gets correctly inferred and compiled (matching what already
   works for ordinary functions), while anything ambiguous or non-scalar
   still refuses.

Either way: audit whether this same gap could affect the (currently
scalar-only) generator LOCAL variable type inference too, not just
parameters — the `_infer_simple_expr_ctype`/`_generator_yield_ctype`
"known name→ctype map" mechanism `292f853` added for locals should be
checked for the same "silently defaults to int64_t when uncertain, instead
of refusing" failure mode.
