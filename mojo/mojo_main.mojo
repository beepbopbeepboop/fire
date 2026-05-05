"""
mojo_main.mojo - Bootstrap test: print tokens from input file.

Note: The real mojo_compiler.py and gimple_codegen.py use Python syntax
(self parameters, etc.) that the Mojo parser cannot handle, so they're
skipped in the transitive closure. The bootstrap tests what it can parse.
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
