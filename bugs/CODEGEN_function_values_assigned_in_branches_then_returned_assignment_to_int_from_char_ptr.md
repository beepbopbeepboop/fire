# CODEGEN: a local bound to a function in one branch and to a nested `def` in the other fails at gcc ("assignment to 'int' from 'char *'")

**State: OPEN, found 2026-10-31** while closing `CODEGEN_generator_function_Lib_os`.
Lib/os.py's generators all compile now; `python3 fire.py build Lib/os.py` then
stops at gcc on an ORDINARY function, `_create_environ_mapping`.

Minimal reproduction (`python3 fire.py build c.py`):

```python
import sys

def make(is_win):
    if is_win:
        def check_str(value):
            if not isinstance(value, str):
                raise TypeError("str expected")
            return value
        encode = check_str
        decode = str
        def encodekey(key):
            return encode(key).upper()
    else:
        encoding = sys.getfilesystemencoding()
        def encode(value):
            if not isinstance(value, str):
                raise TypeError("str expected")
            return value.encode(encoding, 'surrogateescape')
        def decode(value):
            return value.decode(encoding, 'surrogateescape')
        encodekey = encode
    return encode, decode, encodekey

e, d, k = make(False)
print(type(e("a")))
```

    gcc: c.py:16:7: error: assignment to 'int' from 'char *' makes integer from
         pointer without a cast [-Wint-conversion]

Line 16 is `encoding = sys.getfilesystemencoding()`: the local is declared `int`
(its first-seen type came from the other branch, where `encode` is the callable
word) and the string result is assigned into it unconverted. CPython prints
`<class 'bytes'>`.

Next step: find where the function-scope declaration for a name assigned in two
branches picks its type (the first branch's `int` word wins) and make the
assignment of a `char *` into an `int`-declared local a reinterpreting cast, as
the coroutine-body emitter already does (`cpp_core._cpp_assign_cast_type`), or
declare the local the join of both branches' types.
