"""
simple_compiler.mojo — bootstrap-only compiler entry point.

For self-hosting bootstrap, export 4 functions called by runtime/compiler_main.c:
  - mojo_gimple(src: String) → String  — returns GIMPLE C code
  - mojo_pyir(src: String) → String    — returns Python IR (C without GIMPLE)
  - mojo_tokens(src: String)           — prints token stream
  - mojo_ast(src: String)              — prints AST

This is a minimal Mojo file that does NOT depend on gimple_codegen
(which still has transpilation issues). Instead, it calls the Python
compiler functions and returns results.

Once gimple_codegen is fully transpiled to production-quality Mojo,
this file will import and call the Mojo versions directly.
"""

from mojo_compiler import tokenize, Parser, compile as mojo_compile

# TODO: Bootstrap blockers:
# 1. simple_compiler.mojo imports from mojo_compiler, but mojo_compiler.mojo
#    functions aren't available at link time (unresolved externals).
# 2. For stage1, we need these as C symbols provided by the runtime, not Mojo imports.
# 3. Once gimple_codegen.mojo transpiles cleanly, import and call it here instead
#    of returning Python IR.
# 4. gimple_codegen.mojo currently has parse errors (complex exception handlers).


fn mojo_gimple(src: String) -> String:
    """Full compilation: Python IR (pre-GIMPLE).

    TODO: Once gimple_codegen.mojo is production-quality, call it here.
    For now, we return the Python IR which the C harness will compile to GIMPLE.
    Eventually this will call the Mojo-compiled gimple_codegen directly.
    """
    return mojo_compile(src)


fn mojo_pyir(src: String) -> String:
    """Python IR (intermediate representation before GIMPLE lowering)."""
    # TODO: Once gimple_codegen works, this should return distinct output from mojo_gimple.
    return mojo_compile(src)


fn mojo_tokens(src: String):
    """Print token stream."""
    for tok in tokenize(src):
        print(tok.kind + " " + repr(tok.value))


fn mojo_ast(src: String):
    """Print AST (abstract syntax tree)."""
    var stmts = Parser(tokenize(src)).parse_module()
    for stmt in stmts:
        print(repr(stmt))
