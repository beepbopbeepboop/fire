# CODEGEN_cpp_path_refuses_expression_position_yield: a `yield` used as a value inside a larger expression is refused on the cpp generator path

## Status (2026-11-01)

**Partially fixed.** A `yield` used as an operand of a simple statement now
lowers on the cpp escape hatch (`coro.pinned('cpp')`, `MOJO_CORO=cpp`):

- `x = yield` / `x = yield v` (the whole right side; `_cpp_assign_received_yield`).
- `x += yield v` (the augmented assignment's operand).
- `print((yield 1))` and any other yield operand of an expression statement.
- `v = (yield 1) + 1`, `return (yield 2)`, and any yield nested in the value
  of an assignment, augmented assignment, expression statement or `return`.

The mechanism is `_cpp_hoist_yield_operands` in `mojo/backend_gimple/cpp_core.py`,
called at the top of `_cpp_stmt`. It hoists each non-root yield into its own
received-value statement (the same lowering `x = yield` uses, so the received
word is the None box and reads go through the tagged-arithmetic guards) and
lowers the statement with that fresh local in place of the yield. The
AugAssign routes a tagged-word operand through the BinaryOp lowering so the
None guard applies. A call evaluated before a hoisted yield in the same
statement would run after the suspension, so that shape is refused rather than
reordered.

Pinned in `run_tagged_word_cpp_tests` (`test_gimple_generator_runner.py`) with
CPython twins: `aug_assign_received_yield_none_cpp`, `call_argument_yield_cpp`,
`return_yield_operand_cpp`. Before the fix the first refused with
`unsupported expression in generator body: YieldExpr`, the second with
`print() argument must be a scalar int64_t/double/_Bool/char* expression`, and
the third with `unsupported expression in generator body: YieldExpr`. The test group's `with coro.pinned('cpp')` block also covered
only part of that function: four `_cpp` tests after it (`none_received_*`,
`none_sent_into_generator_prints_none_cpp`, `value_yield_assignment_cpp`) ran on
the default path. They now run on the cpp path and pass.

### Still refused (open)

A yield in the condition of a compound statement:

- `if (yield 1): ...` -- refused: `unsupported expression in generator body: YieldExpr`.
  The condition is evaluated once before the `if`, so the top-level condition can
  be hoisted; an `elif` condition is only evaluated when the earlier branches fail,
  so it cannot be hoisted to the front of the chain. Next step: hoist the top-level
  `IfStmt.condition` only (the hoist must not descend into the bodies), and lower an
  `elif` condition with its prelude inside the else branch. Confirm the else-branch
  emission goes through `_cpp_stmt` before relying on it.
- `while (yield 1): ...` -- refused. The condition is re-evaluated on every
  iteration, so a hoisted yield needs the loop restructured to
  `while True: <prelude>; if not cond: break`, with `continue` re-running the
  prelude. Next step: same as `if`, through `_cpp_stmt`'s `WhileStmt` branch.

To reproduce: `gimple_codegen.compile_to_gimple_with_cpp(src)` under
`coro.pinned('cpp')` prints the `Unsupported shape(s)` text for the source.

The `send()` gap that would change what these receive is in
`bugs/CODEGEN_cpp_send_emits_default_path_symbol.md`.
