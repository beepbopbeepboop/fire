# CODEGEN: the stack-switch generator body (`__mgco_<name>_body`) carries no `#line` directives, so a `gcc -fgimple` error inside a generator body is reported against the wrong line

Status: OPEN. Filed 2026-11-12 by the worker that stamped every statement line in ordinary function bodies (the per-physical-line `#line` drift in ordinary functions and lambdas, now fixed). That fix covers plain functions and lambdas; generator bodies go through a different emitter, which this change does not touch.

## Symptom

A plain function's lines are now each preceded by a `#line` for their statement. A generator body lowered to the stack-switch form emits its statements with no directive at all, so GCC numbers its lines from whatever `#line` precedes the function in the `.ci`.

Reproduce (`tools/swarm.py` has a generator-expression hoisted as `__genexp_0` that stays on the stack-switch path; its body unpacks `c, s` pairs from a dict's items):

    python3 -c "from gimple_codegen import compile_to_gimple; import sys; print(compile_to_gimple(open('tools/swarm.py').read(), do_imports=False, filename='tools/swarm.py'))" | grep -n "__mgco___genexp_0_body" -A 40

The body `void __mgco___genexp_0_body (int64_t __c)` (around line 2330 of the output) has ~54 statement lines and zero `#line` lines. The directive count for the whole file is unchanged by the body, so an error in it is reported against the enclosing function's last directive.

## Measured

`tools/swarm.py` through `test_line_directives_per_generated_line._unstamped_statement_lines` after the fix: 59 unstamped statement lines, 54 of them in `__mgco___genexp_0_body`, 5 are module scaffolding (`_mojo_classattr_init ();`, the `_toplevel` `static int _ran` guard), which is not statement code and is not part of this bug.

## Where it is emitted

The body is produced by the stack-switch lowering (`mojo/middle/coro.py`, `body_name = f'{base}_body'` near lines 4734 and 4772). Its statements are not produced by `emit_stmts.gen_stmt`, so the directive stamp that `emit_infra._emit_raw` applies (from `gen._stmt_line_directive`) is never set for them. `grep '#line' mojo/middle/coro.py` finds nothing.

The C++20 companion path (`_mojogen_*` resume/start/destroy, `gimple_cpp_*` / `cpp_async.py`) is a separate emitter with its own (also incomplete) line handling, and is out of scope here.

## Fix (next step)

1. In `mojo/middle/coro.py`, where the `_body` function's statements are emitted, set `gen._stmt_line_directive` per statement the way `emit_stmts.gen_stmt` does (`#line <node.line> "<filename>"`, restored on exit), or route the statements through `gen_stmt` so the single stamp covers them. Prefer routing through `gen_stmt`: one mechanism, not a parallel one.
2. Synthetic nodes built by the generator-expression desugaring (`fire_compiler.py` `genexp_body`) already carry `line=`/`col=`; confirm the stack-switch lowering keeps those lines on the nodes it emits.
3. Test: add a case to `test_line_directives_per_generated_line.py` with a generator (`def counts(xs): for x in xs: yield x`) on the stack-switch path, asserting every statement line in the `__mgco_*_body` function is preceded by a `#line` naming its source line. Note that the sample generator in the current probe goes to the C++ companion (it raises `_refuse_dropped_companion` from `compile_to_gimple`), so the test program must be one the stack-switch path accepts; find it first with `grep -n "__mgco_" mojo/middle/coro.py` and the eligibility check there.
4. Byte-identity: the stripped output (`#line` lines removed) of a generator-containing module must be identical before and after (`cmp`).

## Done when

`python3 test_line_directives_per_generated_line.py` (extended with the generator case) passes, and the stripped-output `cmp` of `tools/swarm.py` is identical before and after. Then delete this doc in that commit.
