"""
mojo_main.mojo — compiler API entry points.

No OS interface here; all of that is in runtime/compiler_main.c.
This file exposes four symbols that compiler_main.c calls into:

    mojo_gimple(src)  -> String   full compilation pipeline
    mojo_pyir(src)    -> String   Python IR (pre-GIMPLE intermediate)
    mojo_tokens(src)             print token stream to stdout
    mojo_ast(src)                print AST to stdout
"""

from mojo_compiler import tokenize, Parser, compile as mojo_compile
from gimple_codegen import compile_to_gimple


fn mojo_gimple(src: String) -> String:
    return compile_to_gimple(src)


fn mojo_pyir(src: String) -> String:
    return mojo_compile(src)


fn mojo_tokens(src: String):
    for tok in tokenize(src):
        print(tok.kind + " " + repr(tok.value))


fn mojo_ast(src: String):
    var stmts = Parser(tokenize(src)).parse_module()
    for stmt in stmts:
        print(repr(stmt))
