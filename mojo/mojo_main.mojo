"""
mojo_main.mojo - Bootstrap test: print tokens from input file.
"""

def main():
    """Entry point when run as mojo script."""
    import sys

    if len(sys.argv) < 2:
        return

    path = sys.argv[1]
    try:
        with open(path) as f:
            src = f.read()
    except:
        return

    # Tokenize and print tokens
    from mojo_compiler import tokenize
    tokens = tokenize(src)
    for tok in tokens:
        print(f"{tok.kind} {tok.value!r}")
