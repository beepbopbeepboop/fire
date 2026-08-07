# HARD BUG: a generator with a struct/class-typed parameter is refused outright, hard-failing the WHOLE top-level module (not a graceful per-function fallback)

## Status (re-verified 2026-08-07, still unfixed)

Re-confirmed still reproducing identically against current master
(after tasks #146/#149/#150/#151/#138/#145 all landed) — none of those
6 fixes touch the parameter-type allow-list. `MOJO_DEBUG=1 python3
mojo.py build .../Lib/dis.py` still shows the exact same refusal:
`_get_instructions_bytes: generator parameter 'arg_resolver' has
unsupported type 'ArgResolver *'`. Considered for this session's item
3 (only-if-time-remains); NOT attempted — the analysis below already
correctly scopes this as genuinely feature-sized (parameter-acceptance
AND body-side struct-method-call support need to land together, or the
failure just moves one step later per the "What a fix would need"
section), not a narrow fix suitable for the remaining time budget in
this pass. Left for a dedicated future session with a real time budget,
per this project's guidance for tasks explicitly marked this way.

## Status (original)

Unfixed / not attempted — this is a deliberate, documented scope boundary
in `_gen_cpp_generator_unit`/`_gen_cpp_async_unit`, not an accidental bug
in the usual sense (see "Root cause"), so fixing it means genuinely
widening the coroutine codegen's parameter-passing story, not patching a
mistake. Root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135). Confirmed
live on current master (`2b0c4c5`) via `Lib/dis.py`'s real build.

## Symptom

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py
[gimple_codegen] generator '_get_instructions_bytes' not eligible for C++ coroutine path, falling back to honest refusal: _get_instructions_bytes: generator parameter 'arg_resolver' has unsupported type 'ArgResolver *' (only int64_t/double/_Bool/char*/MojoList*/MojoDict*/MojoSet* parameters are supported for compiled generators)
[... repeated for passes 2-4 ...]
[gimple_codegen] relaxed_imports: skipping unsupported functions: _get_instructions_bytes (generator function(s), contain a `yield`/`yield from`)
Error building: cannot compile module: function(s) _get_instructions_bytes (generator function(s), contain a `yield`/`yield from`) — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead
RuntimeError: cannot compile module: function(s) _get_instructions_bytes (...)
```

`mojo.py build`'s exit is a hard failure (RC=1, no object file produced)
DESPITE the error text claiming "falling back to interpreting this
module from source instead" — that fallback behavior is real for
**imported** modules (`gen_module`'s "relaxed imports" degrade-gracefully
path — see the `[gimple_codegen] relaxed_imports: skipping unsupported
functions` debug line right above, which IS a graceful per-function skip
for a module reached via import), but is NOT honored for the **top-level
file actually passed to `mojo.py build`** — `build_executable` treats
`gen_module`'s `RuntimeError` as fatal for that one file, full stop. This
exact "message promises graceful fallback, CLI path doesn't actually take
it" mismatch is independently corroborated by
`bugs/hard/CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`'s
own Symptom section, so it's a recurring, general characteristic of this
failure mode across this whole cluster, not unique to `dis.py`.

## Root cause

`_gen_cpp_generator_unit`'s parameter-support step (`gimple_codegen.py`)
only accepts parameters whose resolved C type is one of `int64_t`,
`double`, `_Bool`, `char *`, `MojoList *`, `MojoDict *`, `MojoSet *` — any
OTHER resolved type (concretely: a pointer to a user-defined
`struct`/`class`, e.g. `dis.py`'s own `ArgResolver` class) raises
`_UnsupportedGeneratorShape` and the whole function is refused. This is
an explicit, documented, INTENTIONAL scope limit — the method's own
docstring says: *"string/struct/pointer parameters cross the C++/C
boundary with lifetime and ownership questions this narrow step
deliberately defers"* — not a bug where the type was supposed to work and
doesn't; the coroutine codegen project simply never widened past scalar/
container types for parameters. The identical restriction (byte-for-byte
same allow-list) is independently duplicated in `_gen_cpp_async_unit`
(plain async functions) and the async-generator step, so this is a
project-wide policy of the whole C++20-coroutine codegen subsystem, not a
one-off omission in the plain-generator path alone.

`_get_instructions_bytes(code, linestarts=None, line_offset=0,
co_positions=None, original_code=None, arg_resolver=None)` in `dis.py`
takes `arg_resolver: ArgResolver = None` — a real, explicitly-typed
(via the object actually passed at every real call site, resolved through
this codegen's own usage-based inference) parameter of a user-defined
class. This is a categorically different situation from the already-
documented "untyped param defaults to int64_t" gap
(`bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s bullet 1): the type here
IS correctly known/inferred (`ArgResolver *`) — it's being explicitly
REFUSED, not silently mistyped.

## Why this is a distinct, high-value finding for this cluster

Because the refusal escalates to a WHOLE-MODULE `RuntimeError` for the
top-level file (see Symptom), a single generator function ANYWHERE with
one struct-typed parameter is enough to hard-fail `mojo.py build` for
that entire file, even if every other function in the file (generator or
not) would otherwise compile cleanly. This makes it a much higher-impact
gap per occurrence than the "gets past eligibility but hits a narrower
.cpp-level type bug" cluster (dyld.py's 5 bullets) — those degrade to
"this one generator's body has a bug", not "the whole file refuses to
build at all".

## What a fix would need

Passing an opaque struct pointer as an ordinary by-value C++20 coroutine
parameter is mechanically straightforward (the compiler-generated
coroutine frame already copies scalar/`MojoList *`/`MojoDict *`/
`MojoSet *` parameters into itself by value today — the same copy
semantics work for any trivially-copyable pointer type, including a
struct pointer, with ZERO additional plumbing beyond widening the
allow-list check). The real work implied by the docstring's own caveat
("lifetime and ownership questions") is likely about what happens
INSIDE the generator body once such a param is in scope — e.g. does
`_cpp_expr`'s `MemberExpr` case support `arg_resolver.get_argval_argrepr
(...)` (a METHOD CALL on a struct-typed generator parameter, not just a
scalar SELF field read, which `_gen_cpp_generator_unit`'s own docstring
already flags as "method calls on self ... are out of this step's scope
and refuse naturally" for the `self` case) — so simply widening the
allow-list would very likely just convert this hard hand-off-time
refusal into a DIFFERENT `_UnsupportedGeneratorShape`/C++ compile error
the first time the body actually USES the struct parameter (calls a
method on it, as `_get_instructions_bytes` does:
`arg_resolver.get_argval_argrepr(op, arg, offset)`). Any real fix should
be scoped to cover both the parameter-acceptance AND the body-side
struct-method-call support together, or it will just move the failure
one step later without actually unblocking the file.

## Repro

Real: `MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/dis.py` — `_get_instructions_bytes`'s `arg_resolver: ArgResolver`
parameter.

Minimal repro sketch (not yet hand-verified in isolation):

```python
class Resolver:
    def __init__(self, base):
        self.base = base
    def resolve(self, x):
        return x + self.base

def gen_vals(r, n):
    i = 0
    while i < n:
        yield r.resolve(i)
        i += 1

def main():
    r = Resolver(10)
    for v in gen_vals(r, 3):
        print(v)
main()
```
Expected (per root cause above): refused at the parameter-type check
(`r`'s resolved type `Resolver *` not in the scalar/container allow-list)
before ever reaching the `r.resolve(i)` method-call question.
