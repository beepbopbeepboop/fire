# CODEGEN: a bracketed generic call to a callee with an inferred (unannotated) return type stubs to 0 in link mode

**Status: open.** Found 2026-11-13 while fixing
`SUITE_comptime_bracket_params_stale_link_mode_message` (doc deleted the same
day). It is pre-existing and unrelated to that fix: the single-TU refusal is
correct, but link mode still answers silently wrong for this shape.

This is the unfixed half of the bug whose doc
(`CODEGEN_bracket_call_to_a_runtime_paramless_function_is_a_zero`) was deleted
by `ec8da836c` ("refuse bracketed call to paramless function instead of 0").
That doc's defect 2 read "in link mode, a callee with no runtime parameter is
not specialised", and the fix commit only added the single-TU refusal. The
repro below shows the characterisation was also wrong: a **return annotation**
is what decides it, not the runtime-parameter count.

## Repro (measured, 2026-11-13)

`.tmp/probe_matrix.mojo`:

```mojo
def a[T: Int]() -> Int:
    return T

def b[T: Int]():
    return T

def c[T: Int](x: Int) -> Int:
    return T + x

def d[T: Int](x: Int):
    return T + x

def main():
    print(a[7]())
    print(b[7]())
    print(c[7](1))
    print(d[7](1))
```

| call | interpreter (`fire.py run`) | link mode (`fire.py build`) | why |
|---|---|---|---|
| `a[7]()` — no runtime params, `-> Int` | `7` | `7` | works |
| `b[7]()` — no runtime params, no return annotation | `7` | **`0`** | stub |
| `c[7](1)` — one runtime param, `-> Int` | `8` | `8` | works |
| `d[7](1)` — one runtime param, no return annotation | `8` | **`0`** | stub |

Commands:

    $ python3 tools/memslot.py --gb 8 --label x -- python3 fire.py run .tmp/probe_matrix.mojo
    7
    7
    8
    8
    $ python3 tools/memslot.py --gb 8 --label x -- python3 fire.py build .tmp/probe_matrix.mojo -o .tmp/probe_matrix.exe
    $ ./.tmp/probe_matrix.exe
    7
    0
    8
    0

The single-TU path refuses all four (that is the pinned behaviour in
`test_comptime_bracket_params.py::test_paramless_function_bracket_refused_
in_single_tu`), so the silent `0` is link mode only — the path
`driver.compile_program`/`fire build` uses by default.

It also means the single-TU refusal's message, "…needs the generic
instantiated, which the single-unit path does not do; link mode (fire build)
does", is false for the exact source the pinned test uses
(`def a[T: Int]():\n    return T`): `fire build` on it prints `0`, while
`fire run` prints `7`.

## Where to look

The emitted C has the template body and the call-site stub, i.e. no
instantiation was materialized for the call. The in-TU pre-pass
(`mojo/backend_gimple/elab_intu.py`) seeds a function instantiation from a
call root only when `_fn_args_are_types(...)` accepts the bracket arguments;
a value parameter like `7` for `T: Int` is not a type, so the seed declines
and link mode falls through to `_lower_call`'s `(int64_t)0` stub
(`mojo/backend_gimple/emit_calls.py`, the "indirect call via SubscriptExpr"
path). The `-> Int`/no-annotation difference suggests the return type is what
makes the elaborated body/type usable at the call site; compare the two
emitted bodies for `b[7]` and `a[7]` (an annotated and an unannotated
parameterless callee) before changing anything.

## Exact next step

1. Pin the behaviour first: in `test_comptime_bracket_params.py`, add a test
   that builds `def f[T: Int](x: Int):\n    return T + x\n\ndef main():\n
   print(f[7](1))\n` through the existing `_build_and_run` helper (link mode)
   and asserts stdout `8`. It fails today with `0`.
2. Then make it pass by materializing the instantiation from the callee's
   inferred return type, or — if that is not reachable without a broader
   change — make link mode refuse this shape with the same honest diagnostic
   instead of emitting the stub. Do not widen the existing refusal to
   imported names: that took 180 stdlib modules down (measured 2026-10-27,
   see the comment in `_lower_call`).
3. Run the stdlib compile before landing a codegen change here; this file is
   unregistered, so no bucket would see a regression.
