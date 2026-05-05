"""Interpreter-based compiler stub for bootstrap.

The actual implementation is in Python mojo_compiler.py and gimple_codegen.py.
This file just provides Mojo-compatible signatures.
"""

class Token:
    pass

class Parser:
    pass

def tokenize(src):
    """Tokenize (stub - actual work in Python)."""
    return ""

def compile(src):
    """Compile via interpretation (stub - actual work in Python)."""
    return ""

def mojo_gimple(src):
    """Generate GIMPLE C from Mojo source.

    Implementation: calls Python gimple_codegen.GimpleGen().gen_module()
    via the Python C API in runtime/compiler_main.c.
    """
    return "int main() { return 0; }"

def mojo_pyir(src):
    """Python IR (intermediate representation)."""
    return mojo_gimple(src)

def mojo_tokens(src):
    """Print tokens."""
    pass

def mojo_ast(src):
    """Print AST."""
    pass
