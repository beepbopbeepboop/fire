# CODEGEN (A3 stack-switch): `yield <identifier-or-member-expr>` always
defaults to int64_t, silently truncating float/string values

## Status (2026-09-25 — the non-unanimous residual is now an HONEST REFUSAL on both backends; the silent miscompile is gone)

The last remaining item ("the fully-unannotated, non-unanimous case") no
longer silently produces wrong values. This session also **corrected two
factual claims this doc had been carrying**, both of which change what the
right fix is.

### Correction 1 — the ordinary-function path has no dynamic-value mechanism

The 2026-08-06 analysis reasoned that the fully-unannotated case "needs
per-call-site monomorphization or a boxed/tagged yield-value ABI", partly
because "the ordinary function call path has SOME dynamic-value mechanism a
generator's fixed single-C-type model doesn't share" — i.e. the implicit
suggestion that generators could borrow it.

**It does not exist.** `fn g(x): return x` called `g(3.5)` and `g("hi")`
prints `3` and a pointer decimal, exactly like the generator. There is no
shared mechanism to reuse, and no per-call monomorphization for ordinary
functions either. This is therefore a **cross-cutting limitation of this
codegen's one-C-type-per-slot model**, not a generator-specific gap — which
is why the right move for the generator half is to refuse honestly rather
than to go build a dynamic-value layer that would not fix the ordinary
half anyway.

### Correction 2 — `MOJO_CORO=cpp` was NOT a correct escape hatch here

This doc stated (in four separate places, including its own "Impact"
section) that `MOJO_CORO=cpp` "remains a fully correct escape hatch for any
Mojo program hitting this shape today." **It is not.** The same program
under `MOJO_CORO=cpp` prints the same `3` and the same raw pointer. The two
backends fix one C value-slot type per generator *independently*, so
falling back to cpp bought nothing here.

### What landed

`_scan_callsite_param_kinds` already computed each generator's per-param set
of call-site kinds and silently discarded any set that wasn't a singleton.
It now also records the genuinely-ambiguous ones in a new
`_CALLSITE_PARAM_CONFLICTS` registry, and a new
`_ambiguous_yielded_params(fn, struct_name)` answers the precise question:
which of `fn`'s params are **both** yielded (directly or through an
expression the static env cannot type) **and** carry conflicting call-site
evidence. Both backends consult that one registry:

- **A3 stack-switch** — `_eligible` refuses, so it no longer emits a
  truncating `int64_t` slot.
- **C++ coroutine** — `_gen_cpp_generator_unit` raises
  `_UnsupportedGeneratorShape` for the same generators. Without this the
  build still succeeded via the cpp path and the fix would have been
  invisible end to end (verified: the C++ gate is what makes the
  diagnostic actually reach the user).

So `def g(x): yield x` called with both `3.5` and `"hi"` now **fails to
build** with a message naming the parameter and the reason, instead of
building, exiting 0, and printing `3` / `4366031504`.

The gate is deliberately narrow, and both directions are regression-tested:

- A conflicting param that is **not** yielded still compiles (its value
  never crosses the yield ABI).
- A yielded param whose call sites **agree** still resolves to the right
  type — `g(3.5)`/`g(1.5)` still yields `double`.
- Struct-method generators take the same path (`b.gen(1)` + `b.gen("s")`
  is refused; `b.gen(3)` + `b.gen(5)` is not).

Regression tests: `conflicting_callsite_yield_kind_refused_not_miscompiled`
and `conflicting_callsite_gate_is_narrow` in `test_gimple.py`.

Breadth check, because this changes an eligibility gate that real corpus
code passes through: `python3 compile_stdlib.py` **664/664 passed, 0
unexpected** — the new refusal fires on no stdlib generator (as expected;
the ambiguity needs a yielded *unannotated* param with disagreeing call
sites, and where that occurred the old behavior was already wrong output).
`test_gimple.py` 314/314, `test_gimple_runner.py` 76/76,
`test_gimple_generator_runner.py` 120/120, `test_generators.py` 29/29,
`test_coro_bugs.py` LOWERED=3/RAISE=6 — identical to baseline.

### What is still open

The real fix — a tagged yield-value ABI (box the value with a
`MOJO_TAG_*`-style tag, reusing the mechanism this runtime already has for
nested-tuple slots) — is unchanged and still feature-sized, but it is now
much better scoped than when this doc first called it that way:

1. **Producer** is small: each yield site emits
   `__mojo_gen_yield_boxed(g, tag, word)` instead of
   `__mojo_gen_yield(g, value)`, reusing `tuple_box_tagged`'s existing
   `[tag, word]` list layout and the `mojo_tagged_int/str/double` accessors.
2. **Consumer** is the whole cost, and the reason it was deferred. The
   consumer's own static type for the loop variable is exactly as unknown
   as the producer's was — `for s in g("hi"): print(s)` gives no static
   hint. So the consumer needs genuine runtime dispatch, at minimum for
   `print`/`repr`, and for anything else (a method call on `s`, `len(s)`,
   arithmetic) it needs a dynamic-value layer comparable to the one the
   ordinary path is also missing (Correction 1). Landing only the producer
   half would buy nothing observable.

So the honest summary is: the silent miscompile is closed, and the
underlying one-C-type-per-slot limitation is now **documented as
cross-cutting** (it affects ordinary functions and generators alike)
rather than recorded against generators alone.

## Status (2026-09-06 — repro 1's direct `yield <param>` case FIXED via call-site type propagation)

`gimple_gen_coro.py` now runs a whole-module scan of a generator's CALL
SITES at the top of `lower()` (`_CALLSITE_PARAM_KINDS`, `_argkind`): when
every call passes a statically-typed argument for an unannotated
positional slot and they all agree, that kind fills the slot in
`_static_env` (the "unanimous cross-call scalar contract" ordinary
functions get from `_infer_param_types` — a stack-switch generator's
fixed single-C-value-kind ABI has no per-call monomorphization, so this
is the only route). `_argkind` resolves literals, unary +/- of a
literal, numeric/string constructor calls, and identifier / `self.<field>`
refs via the caller's own `_static_env`.

- **`def g(x): yield x` called only `g(3.5)`** → now prints `3.5` (was
  `3`). `gs("hi")` → `hi` (was pointer bits). This is repro 1's headline
  shape — verified end-to-end.
- Also fixed the pre-existing `test_gimple_generator_runner.py` failure
  `param_generator_unannotated_double_via_cross_call`.
- Runtime: a small `mojo_coro_gen.c` addition (see the commit).

**Residuals (still default to int64_t):**
1. **Non-unanimous call sites** — `g` called with both `3.5` and `"hi"`
   in one program stays unresolved (correct under the "not unanimous →
   unresolved" rule; genuinely needs per-call-site monomorphization or a
   tagged yield-value ABI — the detailed analysis retained below).

The former `yield <arithmetic on the inferred param>` residual is closed:
`def h(a): yield a * 2` called `h(2.5)` now prints `5.0`, because the
shared compiled `print` path uses the existing Python-repr float helper
instead of `%g`. The fix is covered by `gimple_print_double_python_repr`
and the generator expectations for `2.0`/`5.0` in `test_gimple_runner.py`
and `test_gimple_generator_runner.py`.

`MOJO_CORO=cpp` remains the escape hatch for the non-unanimous residual.

## Status

PARTIALLY FIXED 2026-09-05. The tractable, purely-syntactic half is
landed; the fully-unannotated call-site-dependent half (repro 1) remains
open as a distinct structural gap (see "Not fixed" below).

Found 2026-09-05 while running `test_gimple_generator_runner.py`'s real
compile+link+run suite against the §5.5 cutover (`MOJO_CORO=stackswitch`
now the default — see doc/COROUTINE.html §5.5).

### Fixed (commit — see Claude-Session)

`gimple_gen_coro.py` gained `_static_env(fn, struct_def)` — a best-effort,
purely-syntactic `name -> yield-kind` map built at pre-pass time from the
type sources that ARE in reach before `GimpleGen` exists — and
`_yield_kind(expr, env)` now consults it. Resolved shapes:

* **bare identifier from the generator's own param annotation** —
  `def echo(s: String): yield s` (repro-4-shaped; repro 2's `n: Int`
  path).
* **`self.<field>` from the enclosing struct** — class-body field
  annotations AND `__init__`'s `self.<f> = <annotated-param | literal>`
  assignments. Fixes repro 2 (`yield self.base + i`, `base: Float64`).
* **local `name = <literal>` / `var name = <literal-or-string-concat>`** —
  incl. `FloatLiteral`/`StringLiteral` and a `BinaryOp` fallthrough.
* **list-typed locals** — `xs = [<homogeneous literals>]` and
  `xs = []` refined by `xs.append(<literal>)` / `.insert(...)`; a
  `yield xs[i]` subscript and a `for s in xs: yield s` loop-var binding
  both resolve to the element kind. Fixes repro 3.

`_eligible` / `_generator_value_kind` / `_generator_tuple_slots` /
`_lower_one` all thread the env; `_eligible`/`_lower_one` gained an
optional `struct_def` param so the method path passes the `StructDef`
down.

Beyond the 4 new regression tests in `test_gimple_generator_runner.py`,
this also flipped 3 previously-failing suite cases to PASS
(`generator_method_self_field_double`, `generator_str_list_local_
roundtrip`, and the yield-kind half of `generator_vardecl_string_built_
in_body` — that last one still fails on an *unrelated* general
`"s" + String(int)` mis-stringification bug, reproducible outside any
generator, not in this doc's scope).

### Not fixed — the fully-unannotated case (repro 1)

`def g(x): yield x` called `g(3.5)`, with no type anywhere in `g`'s own
definition, still yields `3` (truncated). Resolving it needs per-call-site
monomorphization of the generator or a boxed/tagged yield-value
representation — a real feature, deliberately out of scope here (see the
detailed analysis retained below). `MOJO_CORO=cpp` remains a correct
escape hatch for this shape.

## Repro

```mojo
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
```
Expected `3.5`; prints `3` (the float truncated to int64_t at the yield
site).

```mojo
class Sampler:
    def __init__(self, base: Float64):
        self.base = base
    def samples(self, n: Int):
        i = 0
        while i < n:
            yield self.base + i
            i = i + 1

def main():
    s = Sampler(1.5)
    for x in s.samples(3):
        print(x)
```
Expected `1.5\n2.5\n3.5\n`; prints `1\n2\n3\n`.

```mojo
def strs():
    xs = ["alpha", "beta"]
    i = 0
    while i < 3:
        yield xs[i % 2]
        i = i + 1

def main():
    for s in strs():
        print(s)
```
Expected `alpha\nbeta\nalpha\n`; prints three raw pointer VALUES as huge
decimal integers (the string's `char *` bit pattern reinterpreted as
int64_t) — same root cause, `_yield_kind`'s 'p' (pointer/string) branch
never fires either.

## Root cause (traced)

`gimple_gen_coro.py`'s `_yield_kind(expr)` — the Layer-1 pre-pass's
best-effort static type guess for a yielded value, used to pick the
generator's SINGLE fixed C value-kind ('i'/'p'/'d', `_KIND_TO_SLOT_CTYPE`)
— only recognizes `StringLiteral`/`FloatLiteral`/`IntLiteral`/`BoolLiteral`
and a `BinaryOp` of two such kinds (recursing on `.left`/`.right`). It has
**no case at all** for a bare `IdentExpr` (a parameter or local variable
reference) or a `MemberExpr` (`self.<field>`) — both fall through to the
function's final `return None`, which every caller then treats as "can't
tell" and defaults to `'i'` (`_KIND_TO_SLOT_CTYPE[None] == 'int64_t'`).

This module runs as an AST pre-pass **before** `GimpleGen` (the real
type-inferring compiler) exists (see the module's own top-of-file
docstring), so it has no access to `struct_field_types`/inferred local
types — by design, for the whole file's other rewrites. But two narrower,
purely-syntactic type sources ARE available at this stage and currently
unused by `_yield_kind`:

1. **The enclosing function's own parameter type annotations**
   (`fn.params`, a `(name, ann)` list) — `def samples(self, n: Int)`.
   A bare `yield n` (or a `BinaryOp` involving `n`) could resolve `n`'s
   kind from its own annotation, no cross-function work needed.
2. **A struct's own `__init__`-assigned field type**, when the yielded
   identifier is `self.<field>` and `__init__` does `self.<field> =
   <annotated-param>` (or the field itself carries a class-body
   annotation) — resolvable by scanning the enclosing `StructDef`'s
   `__init__` method, which the AST already has fully built at this
   stage.

Neither is wired in: `_eligible(fn, struct_name=None)` (the function that
already threads a `struct_name` string for the "generator method" check)
never passes the struct's own AST or `fn.params`' annotations down into
`_yield_kind`, and `_generator_value_kind(fn)` calls `_yield_kind(n.value)`
with no context parameter at all.

The **fully unannotated** case (`def g(x): yield x` called `g(3.5)`, no
type anywhere in `g`'s own definition) is a **different, harder,
genuinely structural** gap: resolving it needs either (a) per-call-site
monomorphization (a distinct `g` C symbol per distinct argument-type
combination — a real feature, this codegen has no notion of generic/
untyped-param specialization for a *generator* today, unlike ordinary
functions which apparently DO handle a Float64 argument to an untyped
param correctly per a same-shape non-generator repro checked during this
investigation — the ordinary function call path has SOME dynamic-value
mechanism a generator's fixed single-C-type `_KIND_TO_SLOT_CTYPE` model
doesn't share), or (b) a fully boxed/tagged generic yield-value
representation (this codegen's fixed choice of `int64_t`/`char *`/
`double` per generator is deliberately narrower — see this file's own
`_KIND_TO_SLOT_CTYPE` comment). Not attempted here; flagged as the harder
half of this doc's scope, likely deserving its own follow-on once the
narrower annotated cases are fixed.

## Impact

Any stack-switch-lowered generator that `yield`s a bare identifier or
`self.<field>` reference — rather than a literal or a binary expression
between two literals — of `Float64`/`String` type silently produces wrong
output (a truncated integer, or a raw pointer value printed as a huge
integer) with **no compile error, no runtime diagnostic**. This is a real
regression class exposed by doc/COROUTINE.html §5.5's cutover (making
stack-switch the default) — every one of these shapes passed under the
old cpp-path coroutine emitter, which apparently modeled a generator's
per-yield value type independently. `MOJO_CORO=cpp` remains a fully
correct escape hatch for any Mojo program hitting this shape today.

## Still open

Only the fully-unannotated case (repro 1) — see "Not fixed" under Status.
The narrower tractable half described in this doc is now landed.
