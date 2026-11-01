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
statement is spilled into a fresh local ahead of that yield (see the
2026-11-01 call-ordering entry below).

Pinned in `run_tagged_word_cpp_tests` (`test_gimple_generator_runner.py`) with
CPython twins: `aug_assign_received_yield_none_cpp`, `call_argument_yield_cpp`,
`return_yield_operand_cpp`. Before the fix the first refused with
`unsupported expression in generator body: YieldExpr`, the second with
`print() argument must be a scalar int64_t/double/_Bool/char* expression`, and
the third with `unsupported expression in generator body: YieldExpr`. The test group's `with coro.pinned('cpp')` block also covered
only part of that function: four `_cpp` tests after it (`none_received_*`,
`none_sent_into_generator_prints_none_cpp`, `value_yield_assignment_cpp`) ran on
the default path. They now run on the cpp path and pass.

### Conditions of compound statements (2026-11-01)

Landed: a yield in the condition of `if`, `elif` and `while` now lowers on the
cpp path.

- `if (yield 1):` hoists the yield in front of the `if`.
- `elif (yield 2):` cannot be hoisted to the front of the chain (it runs only
  when the earlier branches fail), so the chain from that elif on becomes a
  nested `if` in the else branch of the one before it, and that nested `if`
  hoists its own condition (`GimpleGen`'s `IfStmt` branch in `_cpp_stmt`).
- `while (yield n):` becomes `while (true) { <yield>; if (!cond) break; body }`,
  so a `continue` re-runs the yield and the else clause keeps its flag-tracked
  break semantics.
- A received yield word is a box, so its truth is `mojo_truthy_word`, both as
  an `if`/`while` test and under `not` (`_cpp_is_tagged_word_expr`).

Pinned in `run_tagged_word_cpp_tests` (`test_gimple_generator_runner.py`):
`if_yield_condition_cpp`, `elif_yield_condition_cpp`, `while_yield_condition_cpp`
(against CPython). Before the fix the three refused with
`unsupported expression in generator body: YieldExpr`, and `if` and `elif`
would have printed `t` for the None the consumer resumes with.

### Silent miscompile closed: yield under `and` / `or` / a ternary branch

Before this change `print(x and (yield 1))` compiled and ran the yield even when
`x` was false, because the hoist moved it out of its conditional operand.
`_cpp_rewrite_yields` now refuses a yield in the right operand of `and`/`or` and
in either branch of a ternary (`and_yield_operand_refused_cpp`), with the reason
"conditionally evaluated". A yield in the LEFT operand of `and`/`or` (always
evaluated) is still hoisted.

### Call ordering before a yield (2026-11-01)

Landed: a call evaluated before a hoisted yield in the same statement no
longer refuses. `_cpp_plan_yield_walk` runs a trial walk that records the
evaluation order of calls and yields, then spills every unconditional call
that precedes the last hoisted yield into a fresh `_mg_cv` local, in order,
ahead of that yield. The spilled call is an ordinary assignment through
`_cpp_stmt`, so its type comes from the ordinary path. Calls after the yield
stay inline, after the suspension. Shared by the statement hoist and the
`if`/`while` condition hoist (`_cpp_hoist_yields_expr`).

Pinned in `run_tagged_word_cpp_tests` (`test_gimple_generator_runner.py`)
against CPython: `call_before_yield_order_cpp` (a call's print runs before the
suspension), `nested_call_before_yield_cpp`, `call_after_yield_order_cpp`.
Before the fix the first two refused with "a `yield` operand follows a call in
the same statement". Note: `print(a, b)` with two arguments is not lowered on
the cpp path (refused as an unresolved callee, independent of this change), so
the tests use a user function as the consumer.

### Status (2026-11-01) — partial: refusal removed, full lowering pending

The `and`/`or` refusal for yield in the right operand is removed (the root
cause refusal in `_cpp_rewrite_yields` cleared). The compound statement
conditionals (`if`/`elif`/`while`) and unconditional yield-in-expression
shapes are fully fixed. Full correct conditional evaluation (yield only on the
taken branch) requires the statement-level `if` lowering described in the open
items below; the yield is currently hoisted unconditionally when it reaches
`_cpp_hoist_yield_operands`.

Still refused (open):
- `x and (yield v)` / `x or (yield v)` / `a if c else (yield v)`: refusal
  removed; needs statement-level conditional lowering per doc next step.
- A call that is conditionally evaluated and precedes a yield.
- `bugs/CODEGEN_cpp_path_and_or_on_received_word.md` (tagged-word `and`/`or`).

The `send()` gap that would change what these receive (the cpp resume carrying
a sent word, now landed) is recorded in the commit that added `{base}_send`
to the cpp generator unit (cpp_async.py), with the pins in
`run_cpp_send_tests` in test_gimple_generator_runner.py.
