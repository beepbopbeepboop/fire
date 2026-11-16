# GPU offload validation modular - part 7: `compile_info` must refuse a kernel that cannot be sliced out as an exported symbol

Parent: `bugs/hard/GPU_offload_validation_modular.md`. This part owns the
`compile_offload_missing_symbol_error.mojo` row and the piece of infrastructure
the row's "next step" names: `std.compile.compile_info` currently auto-stubs to
`0`, so every compile-time offload case silently succeeds.

## Goal

A `compile_info[...]` request whose kernel argument is not a statically
nameable function must be refused with the exported-symbol diagnostic
(`cannot slice out exported symbol`), instead of the whole construct evaluating
to `0` and exiting 0.

The canonical Modular case (`compile_offload_missing_symbol_error.mojo`) slices
a kernel instantiated with a runtime function pointer — `get_fn[False]()` — and
requires FileCheck to find
`cannot slice out exported symbol ... scale ... n=3`. Its own
`CHECK-NOT: Assertion` half already holds here; the diagnostic half cannot be
reached while `compile_info` is an integer stub.

## Current state (measured 2026-11-15, HEAD `fa105c747`)

`std.compile` is not in the shim table, so it falls through to the generic
`std.*` auto-stub (`_AutoStubNamespace`, `myinterpreter.py:5759`): every
attribute is `0`, every call answers `0`, every subscript answers the same
stub. Probe (`.tmp/probe/cinfo2.mojo`):

    from std.compile import compile_info


    def scale(x: Int) -> Int:
        return x * 3


    def get_fn[flag: Bool]():
        return scale


    def main():
        compile_info[scale, emission_kind="llvm"]()
        compile_info[get_fn[False](), emission_kind="llvm"]()
        print(0)

`python3 tools/memslot.py --gb 8 --label probe-cinfo2 -- python3 fire.py run .tmp/probe/cinfo2.mojo`
prints `0` and exits 0 — including for the runtime-pointer kernel, which is the
case that must be refused. Nothing in the output distinguishes a valid kernel
request from an unsliceable one.

The compiled path is out of scope here for the same reason the triage gives:
`fire.py <file>` on this probe also prints `0` at exit 0
(`driver error, interpreting instead` is not reached because nothing errors),
and the target/emission modelling it needs is the `modular-target-specific`
work the bundle-order row names.

## Work

1. Register `std.compile` in the shim chain
   (`Interpreter._load_mojo_sibling_module`, `myinterpreter.py:6074`, next to
   the `std.gpu`/`std.math` entries) exporting a real `compile_info`.
2. Give it a comptime reading of its bracket. The interpreter must judge the
   bracket's SYNTAX, not its value: `get_fn[False]()` evaluates to the same
   `MojoFunction` as `scale`, so a value-level `__getitem__` cannot tell them
   apart. Special-case it where the subscript's own AST is still available —
   `Interpreter.eval_SubscriptExpr` (`myinterpreter.py:9555`), which already
   dispatches on `expr.obj`/`expr.attrs` for keyword brackets.
3. Accept a kernel argument that is a bare identifier naming a module-level
   `def` (that is a symbol this tree can name). Refuse anything computed —
   a call, a member, a parametrized reference — with
   `cannot slice out exported symbol` naming the symbol the expression
   mentions (`scale` for `get_fn[False]()`), because that is the symbol the
   canonical case's FileCheck matches.
4. Keep `compile_info`'s existing keyword spellings working
   (`emission_kind="llvm"`, `target=...`) — the request still evaluates to a
   value that can stand in for "a mojo build was requested"; this part only
   adds the sliceability check.
5. Add `test_regress_gpu_offload_validation_modular_part7.py`.

## Acceptance

- `compile_info[scale, emission_kind="llvm"]()` on a module-level `def scale`
  runs and the program continues normally (exit 0).
- `compile_info[get_fn[False](), emission_kind="llvm"]()` exits non-zero with
  `cannot slice out exported symbol` and `scale` in the message, and no Python
  traceback.
- `from std.compile import compile_info` resolves to a real object, not the
  integer `0` auto-stub.

## Done when

`python3 test_regress_gpu_offload_validation_modular_part7.py` exits 0. It runs both probes above
through `tools/memslot.py --gb 8` + `python3 fire.py run` (two interpreter runs,
~2 s, < 0.1 GB peak) and asserts the accepted kernel and the refused one.

## Out of scope

- `max.gpu.*` module names (the enqueue/device-passable rows; blocked on the
  MAX host runtime, pinned by `test_gpu_offload_validation_part3.py`).
- Emission-kind and target semantics (`emission_kind="llvm"`,
  `target=A100.target`, NVPTX/PTX emission): the bundle-order and end-to-end
  thunk rows, which need the device toolchain.
- The compiled path's `compile_info` handling.
