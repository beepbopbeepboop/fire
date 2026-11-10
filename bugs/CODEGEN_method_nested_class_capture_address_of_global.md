# CODEGEN_method_nested_class_capture_address_of_global

## Summary
A class declared inside a METHOD that captures an enclosing local (a class
attribute whose value names the method's parameter/local) fails to compile:

```
error: expected expression before '(' token
  mojo_cleanup_push_cattr ((void **) &_classattr_C___cap_n, (void *) _t3);
```

The class-statement emission for a function-scoped class attribute installs a
per-execution cell and saves/restores the `_classattr_<Cls>__<attr>` global
around every call to the enclosing function (`_cattr_restore_begin`). The
save/restore takes the ADDRESS of that global. A TOP-LEVEL function's C body is
never `__GIMPLE`-tagged, so the address is legal there. A struct METHOD's body
is `__GIMPLE`-tagged, and `-fgimple` rejects `&<variable>` in that dialect.

## Reproduce
```python
import sys; sys.path.insert(0, '.')
from test_gimple_runner import compile_mojo_to_gimple_exe
src = '''
class Outer:
    def make(self, n: int):
        class C:
            def get(self):
                return n
        return C().get()

def main():
    print(Outer().make(3))
main()
'''
compile_mojo_to_gimple_exe(src)
```

Measured on this tree (before and after the by-reference class-capture fix)
and on `git archive HEAD`: `RuntimeError: gcc -fgimple compilation failed ...
In function 'Outer_make' ... expected expression before '(' token`.

The trigger is the class-CAPTURE attribute, not "every non-constant class
attribute": a class declared inside a method with a plain non-constant class
attribute and no captured enclosing name (`class C(): name = s + "!"`, with or
without a method reading `self.name`) COMPILES and prints `x!` on both master
and this tree. So the address-of-global save/restore is emitted around the
`_cap_<name>` cell of a capture, which is exactly the shape this doc is
about; a fix for the general non-constant class attribute is not required.

## Expected
`3` — the method-local `n` is captured by the nested class exactly as it is
from a plain function (which works: `def make(n)` compiles and prints 3).

## Next step
In `emit_stmts._gen_stmt_StructDef` / `_cattr_restore_begin`'s emission
(`emit_methods`), the address-of-global save/restore must not be emitted inside
an `__GIMPLE`-tagged body. The simplest correct substitute is to save the
global into a fresh function-local temp and restore it from there at the exit
(no address taken), which is also what
`gimple_codegen`'s `_emitting_plain_func` note says the strict dialect
requires. Then re-run `test_gimple_runner.py`'s nested-class group plus a
method-nested case added beside `gimple_nested_class_method_reads_*`.
