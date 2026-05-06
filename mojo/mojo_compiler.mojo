"""Interpreter-based compiler stub for bootstrap.

The actual implementation is in Python mojo_compiler.py and gimple_codegen.py.
This file just provides Mojo-compatible signatures.
"""

class Token:
    def __init__(self):
        pass

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens

    def parse_module(self):
        return []

def tokenize(src: str):
    """Tokenize (stub - actual work in Python)."""
    return ""

def compile(src: str) -> str:
    """Compile via interpretation (stub - actual work in Python)."""
    return ""

def mojo_gimple(src: str) -> str:
    """Generate GIMPLE C from Mojo source.

    Implementation: calls Python gimple_codegen.GimpleGen().gen_module()
    via the Python C API in runtime/compiler_main.c.
    """
    return "int main() { return 0; }"

def mojo_pyir(src: str) -> str:
    """Python IR (intermediate representation)."""
    return mojo_gimple(src)

def mojo_tokens(src: str):
    """Print tokens."""
    pass

def mojo_ast(src: str):
    """Print AST."""
    pass

class Interpreter:
    def __init__(self):
        pass

    def execute(self, stmt):
        pass
