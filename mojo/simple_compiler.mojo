"""
simple_compiler.mojo — bootstrap-only compiler entry point.

For self-hosting bootstrap, export 4 functions called by runtime/compiler_main.c:
  - mojo_gimple(src: String) → String  — returns GIMPLE C code
  - mojo_pyir(src: String) → String    — returns Python IR (C without GIMPLE)
  - mojo_tokens(src: String)           — prints token stream
  - mojo_ast(src: String)              — prints AST

Current status: Returns Python IR for both gimple and pyir.
- gimple_codegen.mojo still has transpilation issues (see TODOs below)
- For now, stage1/stage2 use Python IR; the C runtime will compile it to GIMPLE
- Once gimple_codegen.mojo is production-quality, import and use it here
- This is a TEMPORARY measure to unblock bootstrap testing; full GIMPLE will follow
"""

from mojo_compiler import tokenize, Parser, compile as mojo_compile

# TODO: Bootstrap blockers (MUST FIX via agent):
# 1. gimple_codegen.mojo parse errors from apex py2mojo transpiler:
#    - Comment placement bug: "# Set → List)" ends up inside function args
#    - Ternary/isinstance parsing: complex expressions with tuples fail
#    - Need systematic transpiler fixes, not local workarounds
# 2. simple_compiler.mojo imports mojo_compiler, but those symbols
#    aren't available at link time (unresolved externals in stage1).
#    Solution: either provide via C API or refactor imports.
# 3. Once gimple_codegen.mojo parses successfully, update this file to:
#    - import gimple_codegen instead of mojo_compiler
#    - call gimple_codegen.gen_module() instead of returning Python IR


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
