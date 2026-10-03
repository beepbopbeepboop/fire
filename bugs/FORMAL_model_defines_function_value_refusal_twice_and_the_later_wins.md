# FORMAL_model_defines_function_value_refusal_twice_and_the_later_wins

**Area:** `formal/model.py` · **Status:** OPEN, unowned, one-line-to-diagnose
· **Found:** 2026-10-03 by `formal15-generic-monomorph`, while running
`test_formal_specialization.py` as a regression check for
`formal/monomorph.py`. Nothing in that branch's change touches
`formal/model.py`.

## What is wrong

`formal/model.py` defines **`function_value_refusal` TWICE**, at two places in
the same file, with different messages:

    25333: def function_value_refusal(name: str, fn_name: str = "") -> str:
    27126: def function_value_refusal(name: str, fn_name: str) -> str:

Python binds the name once, at import, and the **later definition wins**. The
one at 25333 — and the whole of its docstring, which is the longer and more
specific of the two — is dead code.

## What that costs, measured

`test_formal_specialization.py`'s case `a function read as a value is refused by
name` pins the 25333 message with three needles:

    check("read as a VALUE" in text, …)
    check("no value of a function" in text, …)
    check("has no home" not in text, …)

The winning definition's message says "is a FUNCTION, and a function is not a
value on this path" — it contains neither of the first two needles. So:

    $ export PATH=/opt/homebrew/bin:$PATH
    $ python3 test_formal_specialization.py
      FAIL  a function read as a value is refused by name
            [arm64] the refusal is still a placement symptom rather than the construct: …
      formal specialization: PASS=11 FAIL=1

`formal-specialization` is a REGISTERED test in `tools/suite.py` (`extra=`
already lists `formal/model.py`, so the entry is honest about its inputs), which
means the shadowing is being paid for by every gate. The `PASS=11` beside it is
the whole of the remaining coverage of the file, and none of it can see a
duplicate definition — which is why this survived.

Verified by hand on the exact shape of `FUNCTION_AS_VALUE`
(`test_formal_specialization.py:156`), both architectures' messages identical:

    $ python3 fire.py build --formal --no-prove -o .tmp/prog.aout .tmp/prog.mojo
    build: main: 'plain' is a FUNCTION, and a function is not a value on this
    path: it has no representation here — a value is one 64-bit word …

Neither needle is in it.

## Why it is NOT a rename of the test's needles

Two ways to make the red go away, and only one of them is right:

* **Fix the message** (or the test) so the surviving definition matches what is
  asserted. That treats the shadowing as harmless.
* **Delete the dead definition**, keeping 27126, and re-point the test's three
  needles at it. Then 25333's docstring goes with it, and that docstring holds
  the measurement that made the refusal exist at all:

      Measured on this tree, both spellings above were refused with the
      allocator sentence.

  and the `std/algorithm/backend/tile.mojo` argument
  (`workgroup_function[tile_size](offset)` — brackets first, callee-is-a-value
  behind them), which is the paragraph that says *why* the wall behind the
  brackets is a value-model question.

So the two definitions are not interchangeable: one carries the history and one
carries the current wording. The decision — which message is the project's, and
whether the other docstring's content is merged in or lost — belongs to whoever
owns `formal/model.py`'s diagnostics, not to the worker that tripped over it.

## Exact next step

1. `grep -n "^def function_value_refusal" formal/model.py` → two hits; decide
   which one the project means.
2. Merge the surviving one's docstring with the content the other one holds
   (the measurement, the `tile.mojo` argument), so nothing is lost with the
   code.
3. Re-point `test_formal_specialization.py`'s three needles at the message that
   is now real, or restore the 25333 wording. Either way the red goes because
   the shadowing is gone, not because a needle moved.
4. **While there, look for other duplicate top-level definitions in the same
   file.** `formal/model.py` is 27,000+ lines of refusal text and this is the
   one a registered test happened to notice; there is no static check that a
   module defines each name once, and a second copy anywhere in it fails the
   same silent way. `python3 - <<'EOF'` over `ast.parse` of the file, counting
   top-level `FunctionDef`/`ClassDef` names and reporting any count > 1, finds
   them all in one pass; if any other module in `formal/` has one, the same
   reasoning applies to its tests.

## Why this is filed rather than fixed here

`formal/model.py`'s diagnostics are not this worker's area —
`formal15-generic-monomorph`'s claim is `project15:generic-monomorph`, and the
nearest claims over `formal/model.py` are other formal workers' bug-doc sets. A
one-line deletion in the middle of a shared diagnostics file, plus three test
needles, is a collision waiting to happen for no gain on the monomorphizer.