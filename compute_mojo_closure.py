#!/usr/bin/env python3
"""Compute transitive closure of Mojo files imported by a root file.

Usage: python3 compute_mojo_closure.py [root_file]
Outputs: space-separated list of all .mojo files in the closure
"""

import sys
import re
import os
from pathlib import Path

def get_mojo_imports(filepath):
    """Extract Mojo module imports from a file."""
    imports = set()
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            # Match: from MODULE import ... or import MODULE
            for match in re.finditer(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE):
                module = match.group(1)
                imports.add(module)
    except:
        pass
    return imports

def find_mojo_file(module_name, search_dir='mojo'):
    """Find a .mojo file for a given module name."""
    mojo_file = Path(search_dir) / f"{module_name}.mojo"
    if mojo_file.exists():
        return str(mojo_file)
    return None

def compute_closure(root_file, search_dir='mojo'):
    """Compute transitive closure of Mojo imports."""
    visited = set()
    to_visit = [root_file]
    mojo_files = set()

    while to_visit:
        current = to_visit.pop(0)
        if current in visited:
            continue
        visited.add(current)

        # Add .mojo files only
        if current.endswith('.mojo'):
            mojo_files.add(current)

        # Get imports from this file
        imports = get_mojo_imports(current)
        for module in imports:
            mojo_file = find_mojo_file(module, search_dir)
            if mojo_file and mojo_file not in visited:
                to_visit.append(mojo_file)

    return sorted(mojo_files)

if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else 'mojo/mojo_main.mojo'
    closure = compute_closure(root)
    print(' '.join(closure))
