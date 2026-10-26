# A struct parameter called with TWO different structs has no representation
# and degrades to a boxed pointer, silently

## Status

OPEN, and **still exactly as reported** — re-measured 2026-10-04 on this tree,
unchanged, in both pipeline modes:

```
CPython   5
          6
compiled  4319041936          <- a T *
          4339833232          <- a U *, sixteen bytes on, ASLR-dependent
```

Not fixed, deliberately, and this Status records why rather than leaving the
doc to be re-derived. The two options the doc offers are still the two options,
and the choice between them is the doc's own: a decision, not a search. What
has changed since 2026-10-02 is that the CHEAPER one is now measurable before
it is chosen, which is what made the measurement worth repeating.

**The blocker for option (2), "refuse loudly at the call site".** Option (2) is
a `raise` in `mojo/backend_gimple/module_gen.py`'s struct-evidence application
loop, at the `if len(types) != 1: continue` the doc cites — when the slot is
non-unanimous AND the parameter is used as a method receiver. The refusal is
CORRECT (there is no one C signature for two structs) and the module falls back
to interpreting from source, so the answer becomes right. What cannot be
answered without a heavy run is its BLAST RADIUS, and that is exactly what the
doc itself warns about:

> "a blanket refusal of a shape real central stdlib modules use is not a good
> trade"

and `CLAUDE.md` names the measurement that would show it:
`stdlib-dylib`'s `skip <module>:` count must not increase. A worker must not
run `compile_stdlib.py` or `build_stdlib_dylib.py` (tens of minutes, tens of
GB), so **the count before and after this `raise` is the integrator's to
measure**, and until it is measured landing the refusal trades a silent wrong
answer in one fixture for an unknown number of stdlib modules falling out of
the compiled path. That is a worse trade than the bug, which is why it is not
taken blind.

The cheapest way to make it safe, if the integrator wants option (2):

1. Raise only for a slot that is non-unanimous AND is used as a receiver AND
   whose types are all STRUCT pointers (`_sole` non-empty and every member
   ending in `' *'` with its base in `struct_field_types`). A `{'T *', 'int'}`
   disagreement is already handled — `_struct_obs`'s `None` entry is what the
   `_tagged_dyn_` machinery is built for — and must not start refusing.
2. Name the parameter, the callee and the structs in the message, as every
   other refusal in this file does, so the fallback is debuggable from the
   error alone.
3. Then run `stdlib-dylib` and compare the `skip <module>:` count. An increase
   means the shape is too central and option (1) is the answer after all.

**Option (1), a runtime-tagged struct parameter**, is unchanged and still
feature-sized: the value model already has `_mojo_dispatch_getattr` /
`mojo_read_type_tag_safe` and a type tag in every struct's first word, and
`_cpp_expr`'s opaque-local path in `cpp_core.py` already reads a member through
that dispatch. `_CPP_CALLABLE_CTYPE` is the precedent for what a new value
category costs. Note that it is a strict improvement over the status quo in
one respect the refusal cannot reach: it makes the polymorphism *representable*
rather than merely detectable, so a program with one call site would compile
instead of falling back.

**Original report.** Measured 2026-10-02 while fixing the struct-pointer
forwarding chain in `bugs/hard/CODEGEN_param_used_only_as_method_receiver.md`.
Found by writing the test for that fix's VETO and finding the veto has no
cleanly assertable observable, because the shape it protects is already wrong.

## What I ran, and what I saw

```python
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class U:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n + 1

def a(w):
    return w.numel()

def main():
    print(a(T(5)))
    print(a(U(5)))

main()
```

```
CPython   5
          6
compiled  4369504656          <- a T *
          4369504672          <- a U *, sixteen bytes on
```

Measured identically before and after the forwarding change, so it is
pre-existing and not caused by it.

## What is believed

The cross-call struct contract in `mojo/backend_gimple/module_gen.py` resolves
a parameter to a `<Struct> *` only when the call-site observations are
**unanimous** — `if len(types) != 1: continue`, with the comment "Not unanimous
-> the parameter is genuinely polymorphic here and nothing about it is
provable". Here they are `{'T *', 'U *'}`, so `a`'s `w` keeps the `int64_t`
default, `w.numel()` degrades to the generic no-op stub, and each call returns
the argument pointer's own bits. Exit 0, no diagnostic.

The refusal is CORRECT — there is no one C signature for two structs — but
nothing says so at the program level, which is the whole problem. Every other
unsupported shape in this codegen makes itself visible: it raises, emits a
compile error, or falls back to the interpreter. This one quietly computes a
number.

## Why it has no test

The fix for the forwarding chain adds a veto so a hop cannot type a parameter
against its own call sites' evidence. Asserting that veto needs a case where
the veto changes the ANSWER, and the answer on the far side is already an
address. So the property is real, has no observable, and is pinned only by the
code's own comment — which is the "a promise nobody verifies" shape this
project's own conventions exist to end, and it is recorded here rather than
left as a comment that will be read as a test.

## The exact next step

One of these, and which one is a decision rather than a search:

1. **A runtime-tagged struct parameter.** The value model already has a
   `_mojo_dispatch_getattr` / `mojo_read_type_tag_safe` pair and a type tag in
   every struct's first word, and `_cpp_expr`'s opaque-local path
   (`cpp_core.py`'s "generator-body attribute read on opaque scalar local")
   already reads a member through that dispatch. A `T *`-or-`U *` parameter
   would then be declared with a tag and read through the same dispatch, which
   makes the polymorphism representable and turns this from a silent wrong
   answer into either the right answer or a loud refusal. This is a new value
   category — the project has called that "feature-sized" before, and
   `_CPP_CALLABLE_CTYPE` is the precedent for what it costs.

2. **Refuse, loudly, at the call site.** When `_struct_obs` is non-unanimous
   AND the parameter is used as a method receiver, the generator/module could
   raise the way every other unsupported shape does, so the module falls back
   to interpreting from source and the answer is right. This is much smaller
   than (1) and it is the direction every other refusal in this file already
   takes. It also needs a way to say "refuse" that is not
   "whole-module RuntimeError" for a program that mostly works, which is the
   same trade `mojo/middle/coro.py`'s `_lambda_shape_ok` records in prose: a
   blanket refusal of a shape real central stdlib modules use is not a good
   trade.

Whichever is chosen, the acceptance bar is the same either way and is the one
this doc exists to state: **the two calls must not both print a pointer's
bits**, and until then the shape is a silent wrong answer rather than an
unimplemented one.

## Related

- `bugs/hard/CODEGEN_param_used_only_as_method_receiver.md` — the doc whose
  fix named the veto this shape hides behind.
- `bugs/UNTESTED.md` §3.3: "a non-zero exit is the only verdict
  `tools/suite.py` can see", and this is a step below that — the compiled
  answer itself is wrong, and no test in the estate exercises the shape.