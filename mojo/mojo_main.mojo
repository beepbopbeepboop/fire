"""
mojo_main.mojo - Compiler entry points for bootstrap.

These are stubs that will be called by runtime/compiler_main.c.
In the self-hosting pipeline, actual compilation is done by build/mojo (Python).
These stubs can't execute Python code in the compiled binary.
"""

def mojo_gimple(src):
    """Generate GIMPLE C from Mojo source."""
    return "/* stage1 stub: use build/mojo for real compilation */"

def mojo_pyir(src):
    """Generate Python IR (intermediate representation)."""
    return "/* stage1 stub: use build/mojo for real compilation */"

def mojo_tokens(src):
    """Print token stream (stub)."""
    print("/* stage1 stub: tokens not available */")

def mojo_ast(src):
    """Print AST (stub)."""
    print("/* stage1 stub: AST not available */")
