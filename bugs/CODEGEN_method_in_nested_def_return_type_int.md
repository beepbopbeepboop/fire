# CODEGEN_method_in_nested_def_return_type_int

## Summary
A method of a class declared inside a NESTED `def`, returning a MODULE
global, is emitted with C return type `int` while the call site assigns the
result to `int64_t`. gcc rejects the mismatched `__GIMPLE` call:

```
error: invalid conversion in gimple call
  _t2 = C_get (_t1);
```

Measured identically on this branch and on its merge base (both fail; no
relation to the by-reference class-capture change).

## Reproduce
```python
import sys; sys.path.insert(0, '.')
from test_gimple_runner import compile_mojo_to_gimple_exe
src = '''
G = 4

def outer():
    def inner():
        class C:
            def get(self):
                return G
        return C().get()
    return inner()

def main():
    print(outer())
main()
'''
compile_mojo_to_gimple_exe(src)
```

The SAME class written directly in `outer` (`def outer(): class C: ...`) and
the same method in a module-level class both compile and print `4`. So the
trigger is the nested-`def` hop, not a `return <module global>` method.

Generated C on the failing shape:
```c
int C_get (C *);
...
int __GIMPLE C_get (C * self)
{
  int _t1;
  _t1 = G;          /* G is int64_t at module scope */
  return _t1;
}
```
while the caller declares `int64_t _t2; _t2 = C_get (_t1);`.

## Expected
`4`, with `C_get` returning `int64_t` (the direct and module-class shapes do).

## Next step
Find which inference pass types the hoisted method's `return G` as `int`
only when the class came through a nested `def`. `_quick_type` /
`_infer_func_return_type` should see the module global `G` registered as
`int64_t` by the time the hoisted copy's method body is inferred. Start at
the method return-type inference in `mojo/middle/exprtypes.py` and print the
`_quick_type(G)` answer for the hoisted copy; a candidate is that the lifted
`inner` body's struct methods are inferred before the module's global
`_global_var_types`/`var_types` entries are seeded (the direct class is
inferred after them). Tie the method signature to the same module-global type
the body read uses, then add the repro above beside
`test_gimple_runner.py`'s nested-class group.
