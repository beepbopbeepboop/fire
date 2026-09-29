# A callable-valued parameter default naming an IMPORTED module's function still pads a NULL pointer

**State: OPEN — a live SIGSEGV, one line of the same mechanism the sibling
doc's fix closed.** The fix in
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` taught
`calls_shared._callable_value_symbol` to answer "what C symbol does a
function used as a value mean", and both of its callers — a parameter
DEFAULT and a bare function NAME read — now answer with a real address. It
answers for a **bare name** whose function this compile lowered. It does
**not** answer for a `module.attr` reference, because
`gen.imported_symbols` records the module alias while the member's
function symbol may never be compiled into this translation unit at all,
and padding a NULL there is a crash, not a wrong value.

Found 2026-09-29 while fixing the sibling doc; not fixed there, because it
needs a runtime helper and a decision about what "not available in
compiled mode" should be for a callable — see "What the fix is".

## Repro (six lines, measured)

`.tmp/probe/mod1.py`, verbatim:

```python
import os

def probe(x, *, g=os.walk):
    return g(x)

def main():
    r = probe(".")
    n = 0
    for a, b, c in r:
        n = n + 1
    print(n > 0)

main()
```

```
$ python3 .tmp/probe/mod1.py
True                              # CPython: correct, exit 0
$ python3 fire.py build -o .tmp/probe/mod1 .tmp/probe/mod1.py
... (builds, links, 0 errors)
$ .tmp/probe/mod1
Segmentation fault: 11            # exit 139, no output
```

Expected: `True`. Got: a signal.

## Mechanism

`_default_expr_to_pair` (`mojo/middle/calls_shared.py`) asks
`_callable_value_symbol`, which requires the name to be in
`gen.func_return_types` or `gen._generator_api`. Both are populated from
the functions this compile actually translated. With `do_imports=True` and
`import os`, `gen.imported_symbols` gets `os` but `func_return_types`
never gets `walk` — `os.py` is not a translated Mojo module in this
closure (measured: `[k for k in gen.func_return_types if 'walk' in k]` is
`[]`). So `_callable_value_symbol` returns `None`, `_default_expr_to_pair`
falls through to its documented `('int', '0')` fallback, `g` arrives as
address 0, and `probe`'s body calls it through
`mojo_fnptr_call_1((void *)0, ...)`.

The generated C shows the whole chain:

```c
int64_t probe_e253d6 (char * x, int64_t g)
{
  _t1 = (void *)g;
  _t2 = (int64_t)x;
  _t3 = mojo_fnptr_call_1 (_t1, _t2);   /* g == 0 */
  return _t3;
}
```

## Why it is NOT fixed by the sibling doc's change

`os.walk` may be a function, a struct, or nothing at all in a given
closure, and "resolve it" is a property of the whole import closure, not
of the expression. Padding 0 is the one answer that is always available
and always wrong. The two honest alternatives both need a decision that is
bigger than this fix:

* **Refuse the module.** `gen_module_impl` already escalates an
  ineligible generator into interpreting the whole module from source,
  but that escalation only covers `self._generator_fns` — the ones A3 and
  the cpp path both left alone. A generator A3 already lowered has its
  body emitted as an ordinary `__mgco_<g>_body`, and there is no
  whole-module catch around ordinary function emission to escalate into.
  Adding one is a real change to `gen_module`'s error contract (today a
  `_default_expr_to_pair` problem cannot fail a build).
* **Emit the "unavailable in compiled mode" stub.** This codegen already
  has the convention — `_unsupported_generator_names` weak stubs print a
  diagnostic and return 0 (see `module_gen.py`'s own comment for why they
  are weak definitions rather than declarations). Applying it to a
  callable needs a function with the callee's C signature, which is
  arity- and return-type-dependent; the existing stubs are all
  `int64_t f (...)`, so this needs either a small `mojo_unavailable_
  callable_0..4` family in `runtime/fire_runtime.c` (which then has to be
  accounted for in `test_runtime_header_scan.py`'s expected counts) or a
  variadic stub plus a guard at each call site.

Either way the result is exit 0 with an honest diagnostic, never a signal.

## What the fix is

Preferred: the `mojo_unavailable_callable_N` family, because it is the
established convention and needs no change to `gen_module`'s error
contract. Sketch:

```c
/* runtime/fire_runtime.c */
int64_t mojo_unavailable_callable_0(void);
int64_t mojo_unavailable_callable_1(int64_t);
...
```

with a `mojo_unavailable_callable_name(const char *)` that arms the name
for the next diagnostic, or a per-name pair like the existing weak stubs.
`_callable_value_symbol` then returns
`('void *', 'mojo_unavailable_callable_ptr ("os.walk")')` for the
unresolvable `MemberExpr` case, with the address of the stub. Note that
emitting it needs a real `_new_val` allocation (it is a call, not a
literal), so `_default_expr_to_pair`'s "pair of C text" contract has to
widen — that is the part that wants a design decision rather than a patch.

A bare-name variant (`_walk = some_module_global` where the name is a
constant, not a function) is deliberately NOT in scope: `_default_expr_
to_pair`'s `('int', '0')` for an unresolvable bare name predates any of
this and is indistinguishable, there, from a constant's value. It is a
separate question with a separate (wider) blast radius.

## Next step

1. Decide: runtime stub, or a whole-module escalation for an
   unresolvable callable default.
2. If the stub: add the runtime family, update
   `test_runtime_header_scan.py`'s expected set, and widen
   `_callable_value_symbol` to emit it.
3. Regression test alongside `gimple_callable_valued_parameter_default`
   in `test_gimple_runner.py` (that suite IS in the `check`/`gate` bucket
   as `gimplerunner`), asserting the diagnostic on stderr rather than an
   exit code — the compiled binary still exits 0 by design here.
