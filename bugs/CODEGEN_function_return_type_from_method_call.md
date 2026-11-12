# CODEGEN_function_return_type_from_method_call

## Summary
A function whose only `return` is a call to a USER-CLASS method is emitted
with C return type `int64_t` whatever the method returns. A `double` comes
back truncated: `2.5` prints `2`. The same function returning a `double`
parameter is `double`. Measured identically on this branch and its merge
base, so it is independent of the class-capture work.

## Reproduce
```python
import sys; sys.path.insert(0, '.')
from test_gimple_runner import compile_mojo_to_gimple_exe
src = '''
class C:
    def get(self):
        return 2.5

def mk():
    return C().get()

def main():
    print(mk())
main()
'''
compile_mojo_to_gimple_exe(src)   # prints 2, CPython prints 2.5
```

Generated C:
```c
double C_get (C *);
int64_t mk_f77bd1 (void);          /* inferred from the CALL, not its type */
...
  _t1 = C_get (...);
  _t2 = (int64_t)_t1;             /* truncation happens here */
```

`print(C().get())` directly in `main` is correct (2.5), and
`def mk(x: float): return x` is correct, so the gap is specifically the
return-type inference of a `CallExpr` whose callee is a `MemberExpr`.

## Expected
`2.5`: `mk`'s return type should be the called method's return type.

## Next step
Teach `_quick_type`'s `CallExpr` arm (mojo/middle/resolve_shared.py) to
resolve a `MemberExpr` callee to the method's C return type, via
`func_return_types[<struct>_<method><overload-id>]` (or
`struct_field_types` for a `@property`), before falling back to
`int64_t`. Then add the repro above to `test_gimple_runner.py` beside the
other return-type cases.
