# A `match` arm with several patterns, or a guard, emits `||` / `&&` inside a `__GIMPLE` body

## Status

OPEN. Found 2026-10-29 while fixing the enum-case pattern (`case .PASS:`) on
the compiled path. Not caused by that change: the condition text is built by
the same code before and after it.

## What is wrong

`_gen_stmt_MatchStmt` (`mojo/backend_gimple/emit_stmts.py`) builds each arm's
test as a C expression joined with `||` (several patterns) and `&&` (a guard),
then emits it as one `if (...)`. That is valid C. It is not valid GIMPLE, and a
function whose body is `__GIMPLE` (every struct method, closure, and lifted
body) is checked as GIMPLE by gcc when it is compiled with `-x c`:

    if (_t3 || _t5) goto bb_4; else goto bb_7;     /* '||' not valid in GIMPLE */
    if (_t3 && _t5) goto bb_4; else goto bb_7;     /* '&&' not valid in GIMPLE */

A plain module-level `def` is not a `__GIMPLE` body, so the same text compiles
there, which is why a `def`-only test does not show it.

## Reproduce

    struct K:
        var _v: Int
        def __init__(out self, v: Int):
            self._v = v
        def pick(self):
            __match self._v:
            case 1, 2:
                print('low')
            case _:
                print('other')
    def main():
        K(1).pick()

`compile_to_gimple(src, do_imports=False, filename='m.py')` then
`gcc -fgimple -fsyntax-only -x c -Iruntime out.c` gives
`'||' not valid in GIMPLE before '||' token`. The guard form
(`case 1 if n > 0:` in the same method) gives the same error with `&&`.
Without `-x c` (what `compile_stdlib.py` uses), gcc reads the file as C and
the error does not appear, so the stdlib syntax gate cannot see this.

## Expected

Each pattern test is its own branch, so `||` becomes control flow and the
guard runs only after a pattern matched, as in `match` on the interpreter.
GIMPLE has no `||`/`&&` on a condition; the standard lowering is a chain of
`if (test) goto arm; else goto next_test;` blocks, one per pattern, with the
guard as an `if` inside the arm's entry block.

## Next step

In `_gen_stmt_MatchStmt`, stop joining the pattern tests into one string.
Emit one test block per pattern (the existing `case_bbs`/`next_check_bb`
labels already give the shape), and the guard as its own `if` before the arm
body. Add `test_gimple_runner.py` rows for `case 1, 2:` and `case 1 if n > 0:`
inside a struct method, running them and comparing stdout with the
interpreter's answer.
