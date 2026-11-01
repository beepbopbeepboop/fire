# CODEGEN: the self-hosted compiler binary segfaults (exit -11) compiling a small program with f-strings

## Status (2026-10-31, OPEN, found while verifying a perf change; reproduced on unmodified master)

`test_selfhost.py`'s binary check compiles a two-line program with NO f-string, so it cannot see this. Build the
self-host binary the way that test does (`test_selfhost.build(td)`), then:

    def f(a, b):
        return f"x={a} y={b + 1} z={a * 2}"
    print(f(3, 4))
    name = "w"
    print(f"hello {name} {len(name)}")

    <td>/mojo_selfhost --dump-full f.mojo      ->  exit -11, no .ci
    python3 fire.py --dump-full f.mojo         ->  29,667-byte .ci

Same result on master (`05d55428b`-era tree, binary built from an untouched checkout) and on a tree with a
token-memo edit, so it is not from that edit. f-string interpolation is the one place the compiled compiler
parses source text at codegen time (`emit_exprs._lower_StringLiteral`: `Parser(py_tokenize(text))._parse_expr(0)`,
then `ast_rewriter.rewrite_node`, then `lower_expr`), and an earlier note there records that this path once
lowered every interpolation to the empty string when compiled.

## Status update (2026-10-31, worker bug-mid-codegen-selfhost-binary-segfault): not reproduced here, no fix landed

What this round measured (light-worker budget: no self-host build, so the binary crash could not be reproduced
from the current tree):

- Ran the prebuilt `mojoc` in `mojo-reference/` (built 2026-10-23, an older tree than the one this doc names)
  on the two-function f-string program above, via `memslot --gb 8`: exit 0, 25,643-byte `f.ci`, no segfault.
  Interpolation is lowered correctly: `_slit_10000 = "x="`, `mojo_str_cat` chain over `a`, `b + 1`, `a * 2`,
  and the `hello {name} {len(name)}` line emits its pieces. So the crash is either newer than 10-23 or depends
  on the binary's build, not on the program alone.
- Static wiring of the f-string path checked and consistent: `emit_exprs._lower_StringLiteral` imports
  `Parser`/`py_tokenize` at module scope, calls `gimple_ctypes.ast_rewriter.rewrite_node` (which exists,
  `ast_rewriter.py:957`, and `mojo/middle/types.py:27` re-exports `ast_rewriter`), and wraps the whole
  interpolation in `except Exception`. An exception there becomes a warning plus literal text, so the crash is
  NOT a Python-level exception; it has to be a native fault (a bad pointer or a stack overflow in the compiled
  parser/rewriter) that `except` cannot see.

Next step (needs a self-host build, so it is the integrator's or a heavy worker's to run):

1. Build the binary the way `test_selfhost.build(td)` does and rerun the two-function program with
   `--dump-full`; confirm the exit -11 on the current HEAD (09a309b23) before anything else.
2. Bisect by field: the five interpolations one at a time (`a`, `b + 1`, `a * 2`, `name`, `len(name)`), each
   in its own program, to learn whether it is the field parse (`Parser(py_tokenize(text))._parse_expr(0)`),
   `rewrite_node`, or `lower_expr`. A binary-only fault with the Python path green points at the compiled
   parser's recursion or a boxed-value read.
3. lldb on the binary at the crash (`tools/gdbtool`, HOW-TO-DEBUG.html), then the fix at the faulting frame.
4. Regression: extend `test_selfhost.run_produced_binary` with an f-string program so the `selfhost` step covers it.

## Next step

1. Reduce: which of the five f-string fields crashes (try each alone), and whether it is the field parse,
   `rewrite_node`, or `lower_expr` (lldb on the binary; `tools/gdbtool`, HOW-TO-DEBUG.html).
2. Fix it, then extend `test_selfhost.run_produced_binary` to compile a program that contains an f-string so
   this class is covered by the gate (a green `selfhost` today says nothing about f-strings).
