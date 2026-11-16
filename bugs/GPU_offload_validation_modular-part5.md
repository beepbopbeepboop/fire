# GPU offload validation modular - part 5: an under-supplied specialization is a diagnostic, not a `None`

Parent: `bugs/hard/GPU_offload_validation_modular.md` (its `## Triage (part 1)`
section is the measured matrix). This part is the interpreted half of the
`compile_offload_unbound_param_error.mojo` row; the compiled half is
`GPU_offload_validation_modular-part6.md`.

## Goal

`def param_fn[x: Int, y: Int](...)` applied as `param_fn[2](...)` must be
refused with the missing-parameter diagnostic, at the bracket, instead of
running the body with `y = None`.

The canonical Modular case (`compile_offload_unbound_param_error.mojo`, a
`not %mojo` case) requires `failed to infer parameter 'y'` from a FileCheck run.
This part gets that message out of the interpreter, which is the path a reader
of the case actually reaches here.

## Current state (measured 2026-11-15, HEAD `fa105c747`)

Probe (`.tmp/probe/arity.mojo`):

    def param_fn[x: Int, y: Int](a: Int) -> Int:
        return a + x + y


    def main():
        print(param_fn[2](1))

`python3 tools/memslot.py --gb 8 --label probe-arity-run -- python3 fire.py run .tmp/probe/arity.mojo`
exits 1 with an INTERPRETER TRACEBACK, not a diagnostic:

    Error: unsupported operand type(s) for +: 'int' and 'NoneType'
    ...
      File ".../myinterpreter.py", line 9323, in _apply_binary_op
        return self._wrap_int(left + right)

The mechanism is a deliberate policy in the wrong place: `MojoFunction.__getitem__`
(`myinterpreter.py:2672`) refuses a bracket that supplies MORE items than the
declaration has comptime parameters, and then `_invoke` (`myinterpreter.py:2698`)
binds every comptime parameter still unbound to `None` ("Bind comptime params
that have defaults but weren't provided" — the `if not _found ... define(name,
None)` arm). `None` is right for a parameter that will be INFERRED later from
the call's argument types; it is wrong for one the bracket was supposed to
supply and did not.

## Work

1. In `MojoFunction.__getitem__`, next to the existing "too many" refusal, add
   the "too few" refusal: a comptime parameter that the bracket did not bind
   and that has no declared default (`comptime_param_defaults`, and the `_pd`
   entries the same `_invoke` loop consults) is an error at the bracket.
2. Word it as the canonical case expects —
   `failed to infer parameter 'y' of 'param_fn'` — and raise it through the
   existing diagnostic-record helper (`_rec`/`_note`, near
   `_fieldwise_init_record`, `myinterpreter.py:1310`) so the caret lands on the
   bracket rather than printing a Python traceback.
3. Keep inference working: a call with NO bracket (`param_fn(1)`), and a call
   whose bracket supplies every non-defaulted parameter (`param_fn[2, 3](1)`,
   which prints `6` today), must be untouched.
4. Add `test_regress_gpu_offload_validation_modular_part5.py` next to the other
   `test_*gpu_offload*` files.

## Acceptance

- `python3 fire.py run <probe>` exits non-zero, prints
  `error: failed to infer parameter 'y'` naming `param_fn`, and prints no
  `Traceback (most recent call last)` and no `'int' and 'NoneType'`.
- `param_fn[2, 3](1)` still prints `6` at exit 0.
- A comptime parameter with a declared default is not an error when the
  bracket omits it.

## Done when

`python3 test_regress_gpu_offload_validation_modular_part5.py` exits 0. It runs the two probes
above through `tools/memslot.py --gb 8` + `python3 fire.py run` (two interpreter
runs, ~2 s, < 0.1 GB peak) and asserts the diagnostic on one and `6` on the
other.

## Out of scope

- The compiled path (`python3 fire.py <file>`), which prints `0` and exits 0 on
  the same probe: part 6.
- Inferring a parameter from the call's runtime argument types. Real Mojo tries
  that; this part refuses the under-supplied bracket instead, which is the
  recoverable answer and the one the canonical case asks for.
- `std.compile.compile_info` (part 7).
