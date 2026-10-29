# A same-module call to a module-level generic function in a link-mode build binds the weak "unavailable in compiled mode" stub

## Status

OPEN. Found 2026-10-29 while scoping `CODEGEN_dylib_generic_inline_copies_share_one_symbol`. Not fixed; no code touched.

## Measured

Repro (`.tmp/repro/`, scratch, not committed):

`gen.mojo`:
```mojo
@inline(.always)
def pick[result_type: AnyType = NoneType](x: Int) -> Int:
    return x + 1

def use_a() -> Int:
    return pick(10)
```

`main.mojo`:
```mojo
from gen import use_a, pick

def main():
    print(use_a())
    print(pick[Int](5))
```

`python3 fire.py build -o main main.mojo` (link mode, the default `fire build` pipeline) builds without error. Running it:

```
pick: unavailable in compiled mode0
6
```

- Expected: `11` then `6`.
- `pick[Int](5)` from `main` is correct (6).
- `use_a()` in `gen.mojo`, a bare call `pick(10)` with the default `result_type`, resolves to the extern weak stub, prints the stub's diagnostic into the program's stdout, and returns 0. A silent wrong answer with exit code 0.

Single-TU check (`gimple_codegen.compile_to_c` on the same `gen.mojo`): `use_a` calls `pick_9f63a2`, i.e. the definition is emitted under the parameter-type overload suffix, not the bare name `pick`. So the definition and the link-mode call site disagree on the symbol in some path.

## Why (hypothesis, not yet verified)

The definition's symbol is `_func_csym` = safe name + `_overload_suffix`, which hashes parameter types only (`mojo/backend_gimple/emit_funcs.py` ~2166 and ~2600). The call from `use_a` in the link-mode build appears to be spelled without that suffix, so it falls through to the weak stub from the extern preamble. This is the same spelling-disagreement class as the qualifier bug documented in `test_link_mode.py` (`_local_sibling_module_exports`, `dotted_sibling_import_qualifier_agrees`), but for the suffix, not the qualifier.

## Next step

1. Find the link-mode call-site path that emits `pick` rather than `pick_9f63a2` for a bare call to an imported generic function. Start from `_func_csym` callers in link mode and `_register_link_imports` (`mojo/middle/funcs_shared.py`), and print the emitted call symbol with a `MOJO_TRACE`-style probe.
2. Regression test in `test_link_mode.py` next to `dotted_sibling_import_qualifier_agrees`: the two-module package above; assert `rc == 0`, stdout `11\n6\n`, and no `unavailable in compiled mode` text.
3. Fix so both sides use one spelling (the same `_func_csym`), not a per-site patch.

Related: `bugs/CODEGEN_dylib_generic_inline_copies_share_one_symbol.md` (the dylib-side bare-name collision of the same family).
