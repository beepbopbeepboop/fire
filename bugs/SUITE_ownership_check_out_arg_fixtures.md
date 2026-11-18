# SUITE: `test_ownership_check.py` is red on master — two `out`-parameter fixtures are now parser refusals

**Status (2026-11-17): open. Pre-existing on master (found while landing the
`type_of` unknown-declaration fix; that change does not touch the parser and
this file fails the same way with or without it).**

## What I ran

    python3 test_ownership_check.py

wrapped in `python3 tools/memslot.py --gb 8 --label ownership --` (it is a
parse/diagnostic-only file; no build).

## What I saw

The file stops in `run()` on the first failing REJECT fixture:

    <test>:7:10: error: invalid call to 'fill': unexpected argument
    Traceback ... fire_compiler.py, line 3001, in _check_out_argument_calls
        raise RuntimeError(...)

The fixture is `same_name_aliases_two_out_params_is_exclusive`:

    def fill(out a: Int, out b: Int):
        pass

    def main():
        x = 1
        fill(x, x)

and the next one, `same_name_aliases_out_and_imm_params_is_exclusive`, fails
the same way at `<test>:7:13`. Both were written to make `ownership_check`
report the two `out` parameters as an exclusive (`out`) alias of the same
binding (`x`).

The refusal is real Mojo behaviour, measured and landed in `9b07afdcf`
("out argument: a positional call past the non-out parameters is refused",
2026-11-11): an `out` parameter is initialized by the callee and is NOT a call
argument, so `fill(x, x)` against `fill(out a: Int, out b: Int)` is an
unexpected argument at `x`, before any ownership diagnostic can run. The two
fixtures predate that check and were never updated, so the file's `run()` exits
1 on master.

`counts` in `fire_compiler._module_function_defs` means a name defined twice is
skipped by the out-argument check, but each fixture here defines `fill` once

so both are caught.

## Expected

`python3 test_ownership_check.py` reports `N/N ownership_check fixture cases
passed` and exits 0, with no fixture that the parser refuses before the
ownership pass is reached.

## Exact next step

Decide what the two `out`-aliasing fixtures can still assert, and do it in
`test_ownership_check.py`:

- The aliasing shape they were written for is unreachable now: `out` arguments
  are not passed positionally, so two `out` parameters of one call cannot name
  the same caller binding. Replace them with shapes that reach
  `ownership_check`'s exclusivity check (`mut`/`read` pairs are already covered
  by `same_name_aliases_mut_and_read_params`), or move the `out`-exclusivity
  assertion down to `test_ownership_check.REJECT` shapes that the parser
  accepts (if one exists).
- Do NOT silence `_check_out_argument_calls` or delete the two cases without a
  replacement assertion: the first hides a genuine parser diagnostic, the
  second loses the only `out`-vs-`out` coverage claim the file makes.

Then rerun `python3 test_ownership_check.py` (memslot not required: no
compile) and, since this file is listed in `test_suite.UNREGISTERED`, nothing
else needs registering.
