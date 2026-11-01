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

## Next step

1. Reduce: which of the five f-string fields crashes (try each alone), and whether it is the field parse,
   `rewrite_node`, or `lower_expr` (lldb on the binary; `tools/gdbtool`, HOW-TO-DEBUG.html).
2. Fix it, then extend `test_selfhost.run_produced_binary` to compile a program that contains an f-string so
   this class is covered by the gate (a green `selfhost` today says nothing about f-strings).
