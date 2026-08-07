# CODEGEN_generator_function: Lib/pkgutil.py

## Status (updated 2026-08-06)

**STILL FAILING**, but the specific reason has changed since 2026-07-30
(that note's "yields ModuleInfo objects — non-scalar yield type" framing
no longer matches the current refusal reason).

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pkgutil.py
[gimple_codegen] generator 'walk_packages' not eligible for C++ coroutine path, falling back to honest refusal: calling captured function 'onerror': argument must be a scalar int64_t/double/_Bool/char* expression
Error building: cannot compile module: function(s) walk_packages (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause:** `walk_packages(path=None, prefix='', onerror=None)`
calls its own `onerror` parameter (a passed-in callback) as
`onerror(info.name)` inside the generator body (in an `except
ImportError:`/`except Exception:` handler). The coroutine codegen DOES
have support for calling a captured/parameter function value — the
refusal message ("argument must be a scalar int64_t/double/_Bool/char*
expression") shows the callback-invocation support itself has a
narrower requirement than the generator's own general parameter-type
allow-list: the ARGUMENT expression passed to the callback must
apparently be a simple literal/identifier, not `info.name` (a
`MemberExpr` field access on the loop variable `info`, a `ModuleInfo`
namedtuple instance) — even though `info.name`'s real runtime type
(`char *`) IS itself in the generally-allowed set.

**New, narrow gap — not yet folded into a hard-bug doc** (single
instance so far in this cluster). Distinct from the already-known
struct-typed-param refusal (`bugs/hard/CODEGEN_generator_struct_typed_
param_refused.md`) and the dynamic-`raise` gap (imaplib.py's bug doc):
this one is specifically about the SHAPE of an argument expression at a
captured-callback call site inside a generator, not about a parameter's
own declared type. Flagged for whoever next hits this shape (calling a
generator's own callback/function-valued parameter with a non-trivial —
e.g. member-access — argument expression) to confirm and fold into a
dedicated hard-bug doc.

Not fixed here — narrow-looking but inside the coroutine `.cpp`
call-lowering path, which this task's guidance flags as warranting its
own dedicated verification pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/pkgutil.py
