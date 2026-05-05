#!/usr/bin/env python3
"""Run mojo_main.mojo as Python code (with transitive closure)."""
import sys
import os

# Add project root to path so imports work
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

if len(sys.argv) < 2:
    print("/* no input */")
    sys.exit(1)

mojo_file = sys.argv[1]
sys.argv = ['mojo', mojo_file]

# Import tokenizer to follow transitive closure
from mojo_compiler import tokenize

def collect_transitive_files(entry_path, visited=None):
    """Collect all files in transitive import closure."""
    if visited is None:
        visited = set()

    path = os.path.realpath(entry_path)
    if path in visited:
        return []
    visited.add(path)

    results = []
    base_dir = os.path.dirname(path)
    project_root = os.path.dirname(base_dir) if base_dir.endswith('/mojo') else base_dir

    # Parse the file to find imports
    try:
        with open(path) as f:
            src = f.read()
        tokens = tokenize(src)

        # Simple import detection
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind == 'KW' and tok.value in ('import', 'from'):
                # Found an import statement
                i += 1
                if i < len(tokens) and tokens[i].kind == 'NAME':
                    module = tokens[i].value
                    # Try to resolve it
                    candidates = [
                        os.path.join(base_dir, module + '.mojo'),
                        os.path.join(base_dir, module + '.py'),
                        os.path.join(project_root, module + '.mojo'),
                        os.path.join(project_root, module + '.py'),
                    ]
                    for candidate in candidates:
                        if os.path.exists(candidate):
                            results.extend(collect_transitive_files(candidate, visited))
                            break
            i += 1
    except:
        pass

    results.append(path)
    return results

# Collect all files in transitive closure
files = collect_transitive_files(mojo_file)

# Tokenize and output all
try:
    for filepath in files:
        with open(filepath) as f:
            src = f.read()
        tokens = tokenize(src)
        for tok in tokens:
            print(f"{tok.kind} {tok.value!r}")
except Exception as e:
    print(f"/* error: {e} */")
    import traceback
    traceback.print_exc()
    sys.exit(1)
