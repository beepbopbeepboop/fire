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

## Next step

1. Read the `get_sign` C in the build directory (`fire.py build --dump` / the generated `.c`) and check the tuple slot types at the `return` sites: the `x[byte=1:]` slot should be `Span *`, the `Float64` slot `double`.
2. Check whether the `print(s[0])` read goes through `mojo_list_get_int` (an int accessor on a `double` slot), which is the mis-read the cas-py doc describes.
3. Once the segfault site is named, fix it at the root and add a test that compiles and runs this program (not a text check of the source).
