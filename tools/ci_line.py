#!/usr/bin/env python3
"""Translate gcc error line in .ci file back to source line.

Usage:
    python3 tools/ci_line.py <ci_file> <error_line>

Finds the largest #line N directive smaller than error_line,
then shows line (error_line - N) after that #line directive.
"""

import sys

def ci_line(ci_file, error_line):
    # Read all lines
    with open(ci_file) as f:
        lines = f.readlines()
    
    # Find all #line directives
    line_directives = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#line '):
            try:
                n = int(stripped.split()[1])
                line_directives.append((n, i))
            except (IndexError, ValueError):
                pass
    
    if not line_directives:
        print(f"No #line directives found in {ci_file}")
        return
    
    # Find largest N < error_line
    best_n = None
    best_idx = None
    for n, idx in line_directives:
        if n < error_line:
            if best_n is None or n > best_n:
                best_n = n
                best_idx = idx
    
    if best_n is None:
        print(f"No #line directive before line {error_line}")
        return
    
    # Calculate offset
    offset = error_line - best_n
    target_idx = best_idx + offset
    
    # Show context
    print(f"#line {best_n} at line {best_idx + 1} in {ci_file}")
    print(f"Error at line {error_line} maps to relative line {offset}")
    print(f"Showing line {target_idx + 1} in {ci_file}:")
    print()
    for i in range(max(0, target_idx - 2), min(len(lines), target_idx + 3)):
        marker = ">>>" if i == target_idx else "   "
        print(f"{marker} {i + 1}: {lines[i].rstrip()}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    
    ci_file = sys.argv[1]
    error_line = int(sys.argv[2])
    ci_line(ci_file, error_line)
