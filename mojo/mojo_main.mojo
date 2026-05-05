"""
mojo_main.mojo - Self-hosting compiler.

Stage 1 (Python): Uses mojo_compiler (Python tokenizer, parser, codegen)
Stage 2 & 3 (Mojo): Should eventually use real Mojo implementations
"""

import sys
from mojo_compiler import tokenize

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
