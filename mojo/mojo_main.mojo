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
from codegen import codegen
import ast_nodes

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

    # Tokenize and print tokens
    tokens = tokenize(src)
    for tok in tokens:
        print(f"{tok.kind} {tok.value!r}")
