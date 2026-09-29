# CODEGEN: an unannotated integer local is a 32-bit `int`, not a 64-bit `Int`

## Status (2026-09-28 — OPEN, reproduced, not investigated beyond the repro)

```mojo
def main():
    var a = 0            # inferred
    var b: Int = 0       # annotated
    for i in range(3):
        a += 2000000000
        b += 2000000000
    print(a)             # 1705032704   (wrapped to 32 bits)
    print(b)             # 6000000000   (correct)
```

Built with `fire.py build`; CPython and the annotated form both print
`6000000000`. The generated C declares the inferred local `int` (seen as
`int total;` in every `_gimple_main` dump), so arithmetic on it wraps at 2^31.
Mojo's `Int` is 64-bit and Python's is unbounded; a silent wrong answer, not a
crash, and it depends on whether the author wrote `: Int`.

Found while building benchmark checksums: several sums that fit comfortably in
64 bits printed as wrapped negatives until the accumulator was annotated.

## Next step

Find where the local's C type is inferred from an integer literal (the
`_quick_type`/join machinery) and default it to `int64_t`. The self-hosted
compiler is compiled by this same codegen, so the change needs the full gate
including bootstrap byte-identity.

## Done when

The repro above prints `6000000000` twice, `make gate` green.
