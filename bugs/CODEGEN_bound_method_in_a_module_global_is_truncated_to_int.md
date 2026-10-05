# CODEGEN: a bound method stored in a MODULE GLOBAL is truncated to `int`, and calling it is a SIGSEGV

**Area:** CODEGEN. Found 2026-10-04 while measuring the current state of
`gimplerunner` for `CODEGEN_gimplerunner_red_on_the_merged_batch.md`, whose
red list this is the worst entry of. Not a regression from anything on that
branch: `test_gimple_runner.py`'s own case
`gimple_bound_method_in_a_module_global_keeps_its_convention` has been red
since before it, and its comment claims two fixes for it landed.

## What I ran

`.tmp/repro.py <program>` (single-TU `compile_to_gimple`, `gcc -fgimple`,
`runtime/fire_runtime.c`), against CPython on the same text. The program is
the test case's own fixture:

```python
class C:
    def __init__(self):
        self.k = 9
    def truthy(self):
        return self.k > 4
    def add(self, a, b):
        return self.k + a + b

m = C()
f = m.truthy
print(f())
g = m.add
print(g(1, 2))

def local():
    lf = m.truthy
    lg = m.add
    print(lf())
    print(lg(3, 4))
local()
```

```
CPython  : True / 12 / True / 16      exit 0
compiled : (nothing)                   exit -11
```

## Where the pointer is lost

The emitted C stores the bound method through the globals struct, and the
struct's field is `int`:

```c
typedef struct _root_toplev {
  int f;        /* <-- */
  int64_t g;
  C * m;
} _root_toplev;
```

```c
  _t6 = mojo_bound_method_new (_funcptr_C_truthy, _t3);
  _t9 = (int64_t)(void *)_t6;
  _t7 = (int)_t9;
  _root_globals.f = _t7;                       /* 32-bit truncation */
  ...
  _t12 = mojo_fnptr_call_0 ((void *)_root_globals.f);
```

`g` is `int64_t` and correct, so the two spellings of the same value get
different C types: `f` is the ZERO-ARGUMENT method and `g` takes arguments.
The type comes from the METHOD'S RETURN TYPE —
`gen._global_var_types['f'] == 'int'` while
`gen.func_return_types['C_truthy'] == '_Bool'` and `_TYPE_MAP` maps `bool` to
`int`. So `f = m.truthy` is typed by what `truthy` RETURNS, which is the
wrong question: a bare method access used as a value is a bound method, not
its result.

`gen._actual_types['f']` is already `MojoBoundMethod *` — the test's comment
says the store records it, and it does — so the information exists and the
read is not consulting it. `_declare_var` is first-decl-wins, so the globals
struct keeps the `int` the inference pass wrote first.

## What is NOT the cause

* Not the boxing round trip. `_actual_types['f']` is right, so the
  `MojoBoundMethod *` itself is classified correctly; only the slot's declared
  C type is wrong.
* Not the env/closure family. `local()`'s identical two bindings are the
  control the existing test already asserts, and a lambda captured `double`
  (`gimple_materialized_lambda_keeps_a_double_capture`, filed with this
  branch) survives its own box — a different and now-fixed defect.
* Not a return-type inference problem for `truthy`: `_Bool` is a correct
  return type for a bool-valued method.

## Measured, and the fix is TWO sites, not one — a partial fix does not compile

An attempt that changed only the Phase-1.7 pre-scan
(`module_gen._phase17_value_type`, whose `else` arm declares a global by
`_quick_type(<rhs>)` — the CALL's answer) was measured and REVERTED, because
it turns the SIGSEGV into a gcc error:

```
p.mojo:10:7: error: assignment to 'MojoBoundMethod *' from 'int'
p.mojo:12:9: error: assignment to 'int64_t' from 'MojoBoundMethod *'
```

Both halves of the store have to agree and neither one is currently right:

* the DESTINATION type — `_phase17_value_type`'s final `else` arm, which asks
  `_quick_type(m.truthy)` and therefore gets the method's registered RETURN
  type (`_Bool` -> `int` via `_TYPE_MAP`) rather than the value's own. That
  one fix moves `f` to `MojoBoundMethod *`;
* the SOURCE type at the same store — `gen.lower_expr(node.value)`'s answer
  at module scope is `int` for `f = m.truthy`, even though
  `emit_exprs`'s bare-method-value arm
  (`_lower_bound_method_value`, which returns `'MojoBoundMethod *'`) is what
  builds the value. And `_global_dst_ctype` reads
  `_own_overlay_global_ctype` then `_global_c_decl_types` before
  `_global_var_types`, so a THIRD table can disagree with both; in the
  measured attempt `g`'s destination stayed `int64_t` while its source became
  `MojoBoundMethod *`, which is why that error names the opposite direction.

So read all three of `_phase17_value_type`, `lower_expr` at module scope, and
`_global_dst_ctype`'s precedence, and make them agree — and then check the
other two consumers of the same "what is `recv.method`" question (a struct
field store, and a `global`-declared name written from inside a function),
because a two-site fix that leaves a third reader untouched is the shape that
becomes the next doc.

The narrower question the fix must answer: "is this value a BOUND METHOD?"
`_bound_method_ret_types` does NOT answer it — that table records what such a
value's CALL returns, which is the question `_phase17_value_type` is wrongly
asking. It needs its own predicate, and the local spelling is the control
that says the predicate is answerable: `lf = m.truthy` inside `local()` is
correct today (measured: `True` / `16`, CPython's answer), so
`emit_methods._lower_bound_method_value` produces the right C type somewhere
in that path and the module-scope path is what loses it.

## Regression test

Already exists and is red: `test_gimple_runner.py`'s
`gimple_bound_method_in_a_module_global_keeps_its_convention`. It asserts
CPython's exact text on both the module-global and the local spelling, so
fixing the inference turns it green with no new case; add one only for the
struct-field spelling if the fix touches that path.