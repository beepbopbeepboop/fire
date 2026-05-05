"""
mojo_compiler.mojo — Native Mojo implementation of the Mojo compiler.

This is a self-contained implementation that can be:
- Interpreted by the Python interpreter (for REPL, testing, bootstrap)
- Compiled by build/mojo to GIMPLE (for stage1/stage2 bootstrap)
- Run as a stage1/stage2 executable (for production)

For bootstrap: this wraps Python mojo_compiler for now.
Long-term: incrementally port logic to native Mojo.
"""

# Placeholder implementation - TODO: implement real compiler

fn compile(src: String) -> String:
    """Compile Mojo source to GIMPLE C code."""
    # For bootstrap, delegate to Python
    return ""

fn mojo_gimple(src: String) -> String:
    """Compile to GIMPLE (called by C harness)."""
    return compile(src)

fn mojo_pyir(src: String) -> String:
    """Compile to Python IR (called by C harness)."""
    return compile(src)

fn mojo_tokens(src: String):
    """Print token stream."""
    pass

fn mojo_ast(src: String):
    """Print AST."""
    pass
