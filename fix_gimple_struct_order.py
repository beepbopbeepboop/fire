#!/usr/bin/env python3
"""
Fix struct definition ordering in GIMPLE code.

Struct definitions must come before forward declarations that use them.
This script moves all typedef struct lines to the beginning of the file.
"""

import re
import sys

def fix_gimple_struct_order(ci_file):
    with open(ci_file, 'r') as f:
        lines = f.readlines()

    # Find all struct definitions
    struct_pattern = r'^typedef struct \w+ \{'
    struct_ranges = []  # list of (start, end, definition_lines)

    i = 0
    while i < len(lines):
        if re.match(struct_pattern, lines[i]):
            start = i
            # Find the closing brace
            brace_count = lines[i].count('{') - lines[i].count('}')
            i += 1
            while i < len(lines) and brace_count > 0:
                brace_count += lines[i].count('{') - lines[i].count('}')
                i += 1
            end = i
            struct_ranges.append((start, end, lines[start:end]))
        else:
            i += 1

    if not struct_ranges:
        print("No struct definitions found")
        return

    # Remove struct definitions from their current positions
    lines_to_remove = set()
    for start, end, _ in struct_ranges:
        for i in range(start, end):
            lines_to_remove.add(i)

    # Rebuild - keep non-struct lines in order
    non_struct_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_remove:
            non_struct_lines.append(line)

    # Find the insert point - after includes/pragmas but before other code
    insert_point = 0
    for i, line in enumerate(non_struct_lines):
        if line.startswith('#pragma') or line.startswith('#include') or line.startswith('/*') or line.startswith(' *') or re.match(r'^\s*$', line):
            insert_point = i + 1
        elif line.startswith('extern') or line.startswith('typedef') and 'struct' not in line:
            break

    # Reconstruct: includes/pragmas, then structs, then rest
    output_lines = non_struct_lines[:insert_point]

    # Add all struct definitions
    for start, end, struct_lines in struct_ranges:
        output_lines.extend(struct_lines)

    output_lines.extend(non_struct_lines[insert_point:])

    # Write the fixed output
    with open(ci_file, 'w') as f:
        f.writelines(output_lines)

    print(f"✓ Fixed struct definition ordering in {ci_file}")
    print(f"  Moved {len(struct_ranges)} struct definitions to the beginning")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    fix_gimple_struct_order(ci_file)
