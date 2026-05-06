#!/usr/bin/env python3
"""Link user code with compiled stdlib modules.

When building a Mojo executable, find and link against compiled stdlib
.so files that match the user's imports.
"""

import os
import re
from pathlib import Path

# Find stdlib build directory relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STDLIB_BUILD_DIR = os.path.join(SCRIPT_DIR, 'build', 'stdlib')

def find_stdlib_so_files():
    """Find all compiled stdlib .so files in build directory."""
    so_files = []
    if os.path.isdir(STDLIB_BUILD_DIR):
        for file in os.listdir(STDLIB_BUILD_DIR):
            if file.endswith('.so'):
                so_files.append(os.path.join(STDLIB_BUILD_DIR, file))
    return so_files


def extract_imports(mojo_src: str) -> set:
    """Extract module names from 'from std.XXX import' and 'import std.XXX' statements."""
    imports = set()

    # Match: from std.module import ...
    from_imports = re.findall(r'from\s+std\.(\w+(?:\.\w+)*)\s+import', mojo_src)
    imports.update(from_imports)

    # Match: import std.module
    direct_imports = re.findall(r'import\s+std\.(\w+(?:\.\w+)*)', mojo_src)
    imports.update(direct_imports)

    return imports


def find_matching_so_files(imports: set) -> list:
    """Find .so files that match the imported modules.

    For import 'std.memory.pointer', look for files like:
    - build/stdlib/*memory*pointer*.so
    - build/stdlib/*memory*.so

    Returns absolute paths to the .so files.
    """
    matching = []
    so_files = find_stdlib_so_files()

    for import_name in imports:
        # Convert std.memory.pointer -> look for memory*pointer or just memory
        parts = import_name.split('.')
        pattern_variants = [
            '_'.join(parts),  # memory_pointer
            parts[0],          # memory (first part)
        ]

        for pattern in pattern_variants:
            for so_file in so_files:
                basename = os.path.basename(so_file).lower()
                if pattern.lower() in basename:
                    # Return absolute path
                    matching.append(os.path.abspath(so_file))
                    break

    return list(set(matching))  # Remove duplicates


def get_stdlib_link_flags(mojo_src: str) -> list:
    """Get linker flags for stdlib modules based on imports.

    Returns list of .so file paths to link against.
    """
    imports = extract_imports(mojo_src)
    if not imports:
        return []

    so_files = find_matching_so_files(imports)
    if not so_files and imports:
        # No pre-built .so files found - print diagnostic
        print(f"Warning: Could not find compiled stdlib for: {', '.join(imports)}")
        print(f"  Available .so files: {find_stdlib_so_files()}")
        print(f"  Consider running: python3 build_stdlib.py")

    return so_files


def main():
    """Test the linker."""
    test_code = """
from std.memory import pointer
from std.collections import set
import std.math.constants

def main():
    pass
"""

    imports = extract_imports(test_code)
    print(f"Detected imports: {imports}")

    so_files = find_matching_so_files(imports)
    print(f"Found .so files: {so_files}")


if __name__ == '__main__':
    main()
