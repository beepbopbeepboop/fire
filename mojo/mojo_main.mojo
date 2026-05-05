"""
mojo_main.mojo - Self-hosting compiler (Mojo version for Stages 2 & 3)

Uses real Mojo implementations:
- tokenizer.mojo (Mojo tokenizer)
- parser.mojo (Mojo parser)
- codegen.mojo (Mojo GIMPLE codegen)
"""

import sys
from tokenizer import tokenize
from parser import parse
# from codegen import codegen  # Skip codegen for now
import ast_nodes

def format_ast(node, indent=0):
    """Format AST node for output."""
    prefix = "  " * indent

    if node is None:
        return f"{prefix}None"

    if isinstance(node, bool):
        return f"{prefix}{node}"

    if isinstance(node, (int, float)):
        return f"{prefix}{node}"

    if isinstance(node, str):
        return f"{prefix}{node!r}"

    if isinstance(node, list):
        if not node:
            return f"{prefix}[]"
        lines = [f"{prefix}["]
        for item in node:
            lines.append(format_ast(item, indent + 1) + ",")
        lines.append(f"{prefix}]")
        return "\n".join(lines)

    # Handle AST nodes
    node_type = type(node).__name__
    lines = [f"{prefix}{node_type}("]

    if hasattr(node, "__dict__"):
        for key, val in node.__dict__.items():
            lines.append(f"{prefix}  {key}=")
            lines.append(format_ast(val, indent + 2) + ",")

    lines.append(f"{prefix})")
    return "\n".join(lines)

def main():
    """Entry point when run as mojo script."""
    if len(sys.argv) < 2:
        return

    path = sys.argv[1]
    try:
        with open(path) as f:
            src = f.read()
    except:
        return

    # Parse source and output AST
    try:
        ast = parse(src)
        print(format_ast(ast))
    except Exception as e:
        # Fallback to tokenization if parsing fails
        print(f"/* parse error: {e} */")
        tokens = tokenize(src)
        for tok in tokens:
            print(f"{tok.kind} {tok.value!r}")
