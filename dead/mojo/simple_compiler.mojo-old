"""
simple_compiler.mojo — bootstrap-only compiler entry point.

For self-hosting bootstrap, export 4 functions called by runtime/compiler_main.c:
  - mojo_gimple(src: String) → String  — returns GIMPLE C code
  - mojo_pyir(src: String) → String    — returns Python IR (C without GIMPLE)
  - mojo_tokens(src: String)           — prints token stream
  - mojo_ast(src: String)              — prints AST

Current status: Stub functions. The C harness (runtime/compiler_main.c) provides
the actual implementations by calling back into Python via the Python C API.

This unblocks bootstrap testing without requiring gimple_codegen.mojo or
any working transpiled modules. Once mojo_compiler.mojo parses correctly,
we can import it and move logic here.

TODO: Transpiled modules need fixes:
- mojo_compiler.mojo: uses keyword names as identifiers (out, if, etc.)
- gimple_codegen.mojo: complex structures cause parse failures
- Both require systematic work on compiler_gen.py and apex transpiler
"""

# Stub implementations: C harness provides the real logic
# These are placeholder signatures only; actual work happens in C

fn mojo_gimple(src: String) -> String:
    """Full compilation: Python IR (pre-GIMPLE)."""
    return ""

fn mojo_pyir(src: String) -> String:
    """Python IR (intermediate representation before GIMPLE lowering)."""
    return ""

fn mojo_tokens(src: String):
    """Print token stream."""
    pass

fn mojo_ast(src: String):
    """Print AST (abstract syntax tree)."""
    pass
