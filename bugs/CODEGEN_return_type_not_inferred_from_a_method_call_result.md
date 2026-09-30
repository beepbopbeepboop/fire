# a function's return type is inferred as `int64_t` when its only `return` is a method call — the `char *` is then printed as a raw pointer decimal, exit 0

**State: FIXED for every shape measured 2026-09-30 (the doc's claim
reproduced first, verbatim, at `86d862fc`; see the Status section at the
bottom). The fix is in the ONE place return-type inference makes its own
locals visible, so it cannot be half-applied.** The `VarDecl`-free reading
of the doc's mechanism is right and the root cause is one level below
where the doc looked: `_quick_type`'s `CallExpr`/`MemberExpr`
struct-receiver arm already existed and already read
`gen.func_return_types[<Struct>_<method>]`, gated on the receiver's
`var_types` entry naming a registered struct. It was the RECEIVER that
was unknown, because at return-inference time `var_types` does not hold
this function's locals — so a struct bound to a local was invisible, the
method result fell to the `int64_t` default, and one wrong declaration
turned the value into a pointer decimal at the caller's `print`.

The overlay that already existed for exactly this reason
(`_infer_return_type_with_locals` -> `_prebound_local_ctypes`, formerly
`_container_literal_locals`, `mojo/middle/infra_infer.py`) now also records
a local bound from any call whose result is a REGISTERED STRUCT pointer —
`p = P("a")` (a constructor), `p = mk()` (a factory) and `p = b.get()` (a
method returning a struct) alike — with the type read out of the SAME
`_quick_type` estimator the call site itself uses, so the two agree by
construction. One extra walk round covers the `q = p` alias. The
restriction to a registered struct is what keeps this a strict improvement:
an opaque imported class, whose constructor this codegen does not inline,
keeps the `int64_t` default exactly as before, and no scalar, container or
`char *` answer is touched. Regression test
`gimple_return_type_from_a_method_call_on_a_local` in
`test_gimple_runner.py` covers the doc's three functions plus the alias,
the non-dunder method, a factory, and a struct-returning method, all
against CPython's answers.

Not covered, and unchanged by this: `def g(): p = P("a"); return p` now
declares `g` as `P *` (correct — the old `int64_t` was a value-identity
bug) but the CALLER's `print(g())` still formats the `P *` as a decimal
address. That is the separate "print a struct value" gap, pre-existing and
independent: a bare `p = P("a"); print(p)` in one function prints an
address too, with no function boundary involved. It is not this doc's bug
and is not fixed by it.

## Earlier status — Found 2026-09-29 by `work/hard-fn-import` while fixing
cross-module-import report (see the 2026-09-29 section of
`bugs/hard/README.md`), whose rows 2/4 spell `repr(p)` and would have hit
this had they used `p.__repr__()`. Not a regression from that fix: unchanged
by it, and it reproduces with no imports at all.**

## What I ran

Single-TU (`do_imports=True`) and link mode (`link_mode=True`) through
`gimple_codegen._run_pipeline`, then `gcc -fgimple` + `runtime/fire_runtime.c`,
vs CPython on the same text.

```python
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"

def g():
    p = P("a")
    return p.__repr__()

def h():
    p = P("a")
    return repr(p)

def k():
    p = P("a")
    return p.x

print(g())
print(h())
print(k())
```

## What I saw

```
CPython : R<a>   R<a>   a
compiled: 4372437664   R<a>   a      (single-TU; link mode: 4374321760)
```

Exit 0, no diagnostic, no stub message. `g` is wrong; `h` and `k` are right.

## What I expected

`R<a>` from all three.

## The mechanism, precisely

The difference between `g` and the two that work is not the method, it is
the EXPRESSION KIND the enclosing return type is inferred from. All three
methods return `char *`; only the call-shaped one is lost.

Generated C for `g` (single-TU):

```c
int64_t g (void)            <-- the enclosing function's return type
{
  Parameter * _t1;  char * _t6;  ...
  insp_Parameter___init__ (_t1, _t3, _t4);
  _t6 = insp_Parameter___repr__ (_t1);   <-- the call is correct
  return _t6;                            <-- char * returned as int64_t
}
```

So the CALL SITE is exactly right — the right method, the right argument,
the right mangled symbol, `char *` into a `char *` temp. The enclosing
function's declared return type is `int64_t` instead of `char *`, and that
single wrong declaration turns the value into a pointer decimal by the time
`print` sees it.

`h` gets `char * g (void)` because `repr(...)` lowering returns an explicit
`('char *', temp)` pair, which the return-type inference reads directly;
`k` gets it because a field read carries its declared field type. A method
CALL contributes nothing to that inference.

## What is NOT the cause (checked, so nobody re-derives it)

- **Not** cross-module. Same file and cross-module behave identically;
  measured both, and both wrong in the same way.
- **Not** the dunder name. `p.some_normal_method()` has the same shape; the
  inference never consults any call result.
- **Not** the method's return type being unresolvable. It is registered —
  `func_return_types['P___repr__'] == 'char *'`, and the emitted call
  assigns into a `char *` temp.
- **Not** the `__repr__` dispatch. That was fixed separately (see
  `CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`
  for the parts that are still open); `h` above proves the dispatch works.

## Where

The enclosing function's return type is decided in `gen_module_impl`'s
return-type inference for a `FunctionDef` with no declared return
annotation — the pass that currently derives it from field reads and from
explicitly-typed builtin call results. The method-call branch of that
inference has no case, so the declared `int64_t` default stands.

`bugs/hard/CODEGEN_method_call_on_struct_param_mistyped.md` is the
adjacent, already-closed report — it typed the method CALL on a struct
passed as a free-function PARAMETER. Same area, different question: that
one asked "which method is this?", this one asks "what type does the
enclosing function give back?". Its own docstring records that "the
*return*-value twin of this bug — a function whose only `return` is a
module-level constructor's result — was fixed in the same pass", so the
constructor-result case is closed and the METHOD-call-result case is not.

## Exact next step

Find the pass that assigns an unannotated function's C return type and add
the method-call case, reading the callee's registered return type out of
`gen.func_return_types` under its MANGLED name (not the bare one — the
symbol the call site emits is `<qualifier>_<Name>_<method><suffix>`, and
`_func_csym`/`_struct_method_csym` plus the `_local_def_pts` /
`_imported_def_pts` tier walk are how the suffix half is already resolved
for the call itself).

A measurement worth taking while there, because it decides the shape of
the fix: how many real method calls in this compiler's own `.py` sources
return a `char *`? A `char *` is the only case that can turn into a
pointer DECIMAL, but any typed result is currently dropped, so a fix that
only special-cases strings would leave the general gap.

## Not filed under `bugs/hard/`

It is a silent wrong value, but it is loud in the sense that the answer is
an obviously nonsensical integer rather than a plausible one, and it
affects one expression kind rather than a whole feature.
