# A function returning `Tuple[Float64, type_of(x)]` built from a `StringSlice` segfaults at run time

## Status

OPEN. Real Mojo runs the program and prints the right value; our compiled binary builds and then dies with SIGSEGV (exit 139) on the first `print`. Found while chasing `stdlib/std/collections/string/_parsing_numbers/parsing_floats.mojo:371`, where `get_sign` returns this tuple shape.

## Repro

`gs2.mojo` (scratch copy; the stdlib file is the real site):

```mojo
from std.collections.string import StringSlice

def get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]:
    if x[byte=0] == "-":
        return (-1.0, x[byte=1:])
    return (1.0, x)

def main():
    var s = get_sign("-abc")
    print(s[0])
```

Run: `python3 fire.py build gs2.mojo -o gs2 && ./gs2`

## Expected

`-1.0` (real Mojo, `tools/mojo run gs2.mojo`, 2026-10-28: prints `-1.0`, exit 0).

## Measured

- master `8f3b96d78`: builds; `./gs2` segfaults, exit 139, no output.
- `work/fix-merge-bug-codegen-cas-py-never-compiles-so-the-r2`'s guard (float+pointer tuple refused in `_infer_return_elem_type`) applied on top of master: still builds and still segfaults, exit 139. The two binaries are not byte-identical (same size, 56200 bytes), so the guard changes the emitted code without making this program run.

## Related

A variant that calls `x.byte_length()` before the return builds and then fails at **link**: `Undefined symbols: "_Span_byte_length", referenced from: _get_sign_… `. That is the imported-generic "calls nothing defines" class: see `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`. The repro above avoids it on purpose.

## Root cause (found 2026-10-28)

The crash is at the CALL SITE, not in the tuple. The `get_sign` body is fine
(`MojoList` with a `double` slot and a `Span *` slot). In `main`, the argument
is not converted to a `StringSlice`:

```c
/* gs3.mojo: var text = String("-abc"); var s = get_sign(text) */
text = _t1;                    /* a bare char * (the String lowered to its data) */
_t3 = (int64_t)text;
_t4 = (Span *)_t3;             /* the char * cast to Span *: no Span is built */
_t2 = get_sign_fa3cf4 (_t4);
```

`get_sign` then reads `x->_data` through that pointer. lldb on `gs3-master`:
`EXC_BAD_ACCESS (address=0xa)` at `get_sign_fa3cf4(x=…)`, the first `x->_data`.

Real Mojo performs the `String` -> `StringSlice` conversion (and the literal
one) at the call. Our codegen has no such conversion for a `Span *` parameter:
it casts the argument's value to the pointer type.

Measured: `String("-abc")` argument → real Mojo `-1.0`; ours segfault (exit 139).

## Next step

1. Find where a call argument is coerced to a parameter's declared type
   (`Span *`), and add the `String`/`char *` -> `Span` conversion there (build
   the `Span` with `_alloc_Span`, `_data` = the bytes, `_len` = the length), as
   the codegen already does for other value-to-struct coercions.
2. Add a test that compiles and RUNS `gs3.mojo` and checks `-1.0` (not a text
   check of the source). Then re-check `gs2.mojo` (the literal-argument form).
3. The `Span_byte_length` link error is the separate imported-generic class
   (see the Related section).
