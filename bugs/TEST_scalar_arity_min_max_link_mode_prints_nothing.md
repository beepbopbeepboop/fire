# TEST: `scalar_arity_min_max_params_are_not_containers` fails in link mode (prints nothing)

## Status (2026-10-29, found while landing the decorator-in-block fix)

- Symptom, from a full `python3 test_gimple.py` run (memslot --gb 8):
  `FAIL  scalar_arity_min_max_params_are_not_containers: single-TU, link-mode
  printed '', CPython printed '9 12 6 4096\n'`.
- It fails on the unmodified HEAD `module_gen.py` too, so it is not caused by
  the decorator-block change. The single-TU leg of the test passes; the
  link-mode leg prints nothing.
- The fixture (`test_gimple.py`, `test_scalar_arity_min_max_params_are_not_containers`)
  is `one(xs): max(xs)`, `two(a, b): max(a, b) + min(a, b)`,
  `three(a, b, c)`, and a method `R.read1(self, n): max(n, self.MIN_READ_SIZE)`.
  The zipfile fix that added it is recorded in `bugs/COMPILE_FAIL_zipfile___init__.md`.

## Not yet known

- Whether link mode fails to compile, fails to link, or links and exits
  without printing. The test reports only the empty stdout.

## Next step

1. Run the fixture through link mode alone and read its stderr and exit code,
   e.g. with the `_compiled_stdout(src, 'link-mode')` helper the test uses.
   Do not gate it; one program, memslot --gb 8.
2. If the link fails, the cause is in the link-mode `mojo_max`/`mojo_min`
   symbol handling for multi-argument calls. If it links and prints nothing,
   check the `main` emitted for the four `print` arguments.
3. Fix at the cause and drop nothing from the test; the test already
   requires both pipelines.
