# CODEGEN: a module-scope global bound to a CONTAINER-returning call is declared `int64_t`, so the module does not compile

## Status

OPEN, 2026-10-04, filed from `work/bugs6-1` while closing
`CODEGEN_a_closure_value_in_a_local_does_not_declare.md` (deleted with its
fix). That doc's own symptom is measurably fixed; this is the WIDER gap its
"Exact next step" step 1 said to go and measure, and the measurement is this
doc.

## What I ran, and what I saw

Five module-scope bindings, each through `compile_to_gimple` + `gcc -fgimple`
+ run, against CPython on the same text. All five name their global `f`:

| binding | result |
|---|---|
| `f = {'a': 1}` (a dict LITERAL) | compiles, `1` — correct |
| `f = mk()` where `def mk(): return {'a': 1}` | **COMPILE FAIL** |
| `f = mk()` where `def mk(): return [1, 2]` | **COMPILE FAIL** |
| `f = mk()` where `def mk(): return 5` | compiles, `5` |
| `f = mk()` where `def mk(): return 'ab'` | compiles, `ab` |
| `f = outer(3)` returning a closure (`MojoBoundMethod *`) | compiles, callable |

The dict case, verbatim:

    $ python3 .tmp/probe.py 'def mk():
        return {"a": 1}
    f = mk()
    print(f["a"])'
    COMPILE FAIL: gcc -fgimple compilation failed: .../_toplevel':
    ...:3:19: error: assignment to 'int64_t' {aka 'long long long int'} from
        'MojoDict *' makes integer from pointer without a cast [-Wint-conversion]
    ...:4:7:  error: assignment to 'MojoDict *' from 'int64_t' makes pointer
        from integer without a cast [-Wint-conversion]

and the generated globals struct:

    typedef struct _root_toplev {
      int64_t f;
    } _root_toplev;
    struct _root_toplev _root_globals = { .f = 0 };
    int64_t root__mojo_global_get_f (void) { return _root_globals.f; }

So the field is declared with the generic `int64_t` box while the STORE puts a
`MojoDict *` into it and the READ takes a `MojoDict *` out of it. Both halves
of the pair are already typed correctly at their own sites — this is one
missing declaration in the middle, not two wrong lowerings.

## Why this is a separate doc and not the closed one

The closed doc's title was "a closure value stored in a module-scope local is
never declared, so the file does not compile", and its two defects were both
about `MojoBoundMethod *`: `_root_globals` had no field for `f`, and the call
read the bare `f`. Both are fixed — the same fixture now emits

    struct _root_toplev _root_globals = { .f = (MojoBoundMethod *)0, };
    MojoBoundMethod * root__mojo_global_get_f (void) { return _root_globals.f; }
    ...
    _root_globals.f = _t3;
    _t9 = _root_globals.f;
    _t11 = mojo_bound_method_call_1 (_t9, _t10);

— the field, and every read through it. Pinned by
`test_gimple_runner.py`'s `gimple_module_scope_closure_value_is_declared_and_callable`.
`print(f)` still prints a pointer decimal where CPython prints
`<function outer.<locals>.inner at 0x...>`; that is a FUNCTION-VALUE repr gap
with no doc of its own and it is not this one.

So the answer to the closed doc's step 1 is the second branch of its own
question — "it is 'a global whose type comes from a call', which is much wider
and belongs to the global pre-scan" — and it is narrower still: a call
returning a `char *` and one returning a `double` are both fine, so it is the
CONTAINER ctypes alone.

## What is NOT the cause

* **Not `_infer_return_type`.** The lowering knows the call's result is a
  `MojoDict *` — it emits the coercion to `MojoDict *` at the read and a
  `MojoDict *` value at the store. The return type is available; nothing copies
  it into the globals struct's field list.
* **Not the struct-emission site.** It prints what it is told.
* **Not the `int64_t` box being wrong in general.** It is the documented
  multi-kind container answer (`CODEGEN_multi_kind_global_read_before_the_
  reassignment_reads_the_placeholder`), and `f = {'a': 1}` gets a real
  `MojoDict *` field, so the box is not what a dict-valued global gets by
  default — only what one bound to a CALL does.

## Exact next step

The global pre-scan's value-type row for a module-scope `Name = Call(...)` whose
callee's return type is one of the three container ctypes. The machinery is
the Phase-1.7 global scan beside `_scan_module_level_for_func_attrs`, and the
value is already computed: `gen._infer_return_type(callee)` (or whatever the
sibling global passes call for the same question), gated on
`_gmi_literal_ctype` — which is deliberately *literal-only*, so a call
contributes nothing today.

Two things to decide before writing it:

1. **Which table.** `_global_var_types` (semantic) and `_global_c_decl_types`
   (the C declaration) are separate, and `_own_overlay_global_ctype`'s rule 1
   says "a CONTAINER cdecl beats a scalar own-conclusion" — so a `MojoDict *`
   has to land in `_global_c_decl_types` to be believed, or the two halves of
   the pair disagree exactly as they do now.
2. **Whether a call with an UNKNOWN return type should keep the box.** It must:
   the box is right for a function whose `return` statements disagree, and this
   is the same narrowness `param_binding_ctype` and
   `_gmi_apply_call_site_param_evidence` both state for their own readers.

The bar for landing it: the two fixtures above, in one program, compared
against CPython — and a third that keeps the box, so a "always unbox" fix is
visible.