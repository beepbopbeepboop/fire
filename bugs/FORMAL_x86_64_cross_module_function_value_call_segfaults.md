# x86-64: a comptime specialization through a FUNCTION VALUE across a dylib boundary SIGSEGVs

**Area:** FORMAL, x86-64, the dylib boundary. Found 2026-10-07 on
`work/formal105-docs` while running `test_formal_specialization.py`, whose
`test_the_specialization_reaches_into_another_module_on_both` is RED on x86-64
and green on arm64. **NOT FIXED** — filed, not fixed; it is not this worker's
claim and the failure reproduces with the only change this worker made to the
call path disabled (measured, below).

## What I ran

`test_formal_specialization.py`'s cross-module tile case, both architectures,
against `fire.py run` as the oracle:

```sh
python3 tools/memslot.py --gb 8 --label tile -- python3 fire.py build \
  --formal --no-prove --backend=<arch> -o .tmp/tile/prog.<arch> \
  .tmp/tile/prog.mojo .tmp/tile/lib.mojo
```

`lib.mojo` is `TILE_LIB` and `prog.mojo` is `TILE_PROGRAM` in
`test_formal_specialization.py`:

```python
# lib.mojo
def tile(offset: Int, upperbound: Int,
         workgroup_function: Some[def[width: Int](Int) -> Int]) -> Int:
    var total = 0
    var current_offset = offset
    while current_offset <= upperbound - 3:
        total += workgroup_function[3](current_offset)
        current_offset += 3
    return total

# prog.mojo
from lib import tile

def work[width: Int](offset: Int):
    return offset + width

def main():
    print(tile(0, 10, work))
    return 0
```

## What I saw

| | answer |
|---|---|
| `fire.py run prog.mojo` (the oracle) | `18` |
| arm64 image | `18`, exit 0 |
| **x86-64 image** | **`Segmentation fault: 11`, exit 139, nothing printed** |

Both images build (exit 0, `Built: … [<arch>/macho]`). The x86-64 one crashes
before `print` runs. The single-module spelling of the same construct
(`test_a_specialization_through_a_value_runs_on_both`) is green on both, so the
fault is specific to the call through the word when the CALLEE lives in a
linked dylib.

## What I expected

`18`, exit 0, on both architectures — the shape
`bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`
records as "builds, runs and answers CPython on both architectures, single-module
and across a dylib boundary" (its 2026-10-03 Status). So either that record has
gone stale or this is a regression; a fix should decide which by bisecting the
x86-64 dylib call path.

## Why this is not this worker's change

The only edit `work/formal105-docs` made to the call path is
`model.callee_is_a_module_slot_function` added to both emitters'
`through_value` predicate (a module global holding a function called by name).
Forcing it to return `False` and re-running the failing test reproduces the
x86-64 SIGSEGV identically — measured, predicate disabled:

```
FAIL (predicate disabled): TestFailure [x86_64] the image exited -11:
```

so the defect predates the branch.

## The exact next step

1. Reproduce with the two files above and `--backend=x86_64`.
2. Compare the emitted call site against arm64's `BLR X16` sequence
   (`formal/arm64_codegen.py::_emit_call`'s `through_value` arm) — on x86-64 the
   call is `CALL r64` through R11
   (`formal/x86_64_codegen.py::_emit_call`'s `through_value` arm), and the
   suspicion is the callee word or the argument placement across the boundary
   (`_bind_call_args`, the SysV split) rather than the branch instruction.
3. Check whether the dylib actually loads and whether the crash is in the
   consumer's own prologue or at the branch; `otool -L` on the image and a
   `lldb` backtrace are the cheap next measurements.
4. Whatever fixes it owes `python3 test_formal_specialization.py` green on both
   architectures, and — because it is a compiled-path change — a `make gate`
   before it is done (CLAUDE.md's rule for `formal/x86_64_codegen.py`).
