"""
fire_main.py - Bootstrap compiler (Python version for Stage 1)

Uses Python implementation:
- fire_compiler (Python tokenizer, parser)
- gimple_codegen (Python GIMPLE code generator)
"""

import sys
from fire_compiler import py_tokenize

def main():
    """Entry point when run as Python script."""
    if len(sys.argv) < 2:
        return

    path = sys.argv[1]
    try:
        with open(path) as f:
            src = f.read()
    except:
        return

    # Tokenize and print tokens
    tokens = py_tokenize(src)
    for tok in tokens:
        print(f"{tok.kind} {tok.value!r}")

if __name__ == '__main__':
    main()
