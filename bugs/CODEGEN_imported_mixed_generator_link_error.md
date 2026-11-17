# CODEGEN: an imported generator with mixed str/int call sites is a LINK error, not the stub refusal

## What I ran

    python3 test_module_boundary_regression.py

while verifying an unrelated change to `mojo/middle/methods_shared.py`
(`_is_selfhost_sibling_alias`). The case is
`REFUSAL_CASES`' `imported_generator_mixed_str_int_call_sites_refused`
(`test_module_boundary_regression.py:144`): module `m` defines
`def gen(xs): for x in xs: yield x`, and the root calls it once with
`["p", "q"]` and once with `[1, 2]`.

## What I saw

    6/7 passed
    FAIL imported_generator_mixed_str_int_call_sites_refused: expected a
      refusal containing 'unavailable in compiled mode', got
      '<gcc -fgimple failed: ...
         "__mojogen_m_gen_value", referenced from:
             __gimple_main ...'

The compiled `.ci` names `__mojogen_m_gen_value` and the (companion `.cpp`
that would define it is not part of the single-file compile), so the failure
is a link error, not the weak-stub refusal the test pins.

## Not caused by my change

Measured with the pre-change `_is_selfhost_sibling_alias` monkeypatched back
(`.tmp/old_alias.py`, the function as of `0a932256b`): the same case fails
identically. The other six cases in the file pass on both trees. So this is
red on master's code, not a regression from that edit.

## Expected

The test's contract: a generator whose call sites cannot be typed one way is
REFUSED with a message containing `unavailable in compiled mode` (the test
comments: "Mixed call sites of one generator are NOT a value the compiler can
type"). Today it compiles to a symbol whose definition is discarded.

## Next step

Run the one case in isolation (above) and print the `__mojogen_` lines from
`compile_to_gimple(u_src, do_imports=True, filename=u_path)`.
`gimple_codegen._refuse_dropped_companion` already asks exactly the right
question for this shape (which `_*mojogen_*_(start|resume|value|destroy)`
symbols the `.ci` names vs the companion defines) — but it only raises when
`gen.generated_cpp` is non-empty. For this mixed-call-sites generator the
companion appears to be empty and the symbol is still emitted, so either the
generator was skipped after its call-site text was emitted, or the companion
was dropped earlier in `gen_module`. The fix belongs in that refusal's
precondition: a `.ci` that names a `_mojogen_*` symbol with NO companion
definition must raise the honest refusal the test expects, regardless of
whether `generated_cpp` is empty.

Not fixed here: it is outside the stage1-closure task this round was claimed
for, and `test_module_boundary_regression.py` is not a registered gate job
(`tools/suite.py` does not name it), so it does not gate anyone's landing.
