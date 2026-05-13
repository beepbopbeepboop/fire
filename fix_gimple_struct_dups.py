#!/usr/bin/env python3
"""
Fix duplicate struct typedefs in GIMPLE code.

When multiple source files define the same struct, they get emitted multiple times.
This script deduplicates them, keeping the most complete definition.
"""

import re
import sys

def fix_gimple_struct_dups(ci_file):
    with open(ci_file, 'r') as f:
        lines = f.readlines()

    # Pattern for struct typedef
    struct_pattern = r'^typedef struct (\w+) \{'

    # Track which structs we've seen
    seen_structs = {}  # struct_name -> (start_line_idx, end_line_idx, definition_lines)
    lines_to_remove = set()  # indices of lines to remove

    i = 0
    while i < len(lines):
        match = re.match(struct_pattern, lines[i])
        if match:
            struct_name = match.group(1)
            start = i

            # Find the closing }
            brace_count = lines[i].count('{') - lines[i].count('}')
            i += 1
            while i < len(lines) and brace_count > 0:
                brace_count += lines[i].count('{') - lines[i].count('}')
                i += 1

            # Now i is at the line after the closing brace
            end = i
            definition = ''.join(lines[start:end])
            line_count = end - start

            if struct_name not in seen_structs:
                # First time seeing this struct - keep it
                seen_structs[struct_name] = (start, end, definition, line_count)
            else:
                # We've seen this before
                prev_start, prev_end, prev_def, prev_count = seen_structs[struct_name]

                # Keep the longer definition (more fields = more complete)
                if line_count > prev_count:
                    # New one is longer, remove the old one
                    for j in range(prev_start, prev_end):
                        lines_to_remove.add(j)
                    seen_structs[struct_name] = (start, end, definition, line_count)
                else:
                    # Keep old one, remove new one
                    for j in range(start, end):
                        lines_to_remove.add(j)
            continue

        i += 1

    # Rebuild the file, skipping removed lines
    output_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_remove:
            output_lines.append(line)

    # Write the fixed output
    with open(ci_file, 'w') as f:
        f.writelines(output_lines)

    print(f"✓ Fixed duplicate struct typedefs in {ci_file}")
    print(f"  Found {len(seen_structs)} unique structs")
    print(f"  Removed {len(lines_to_remove)} duplicate lines")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    fix_gimple_struct_dups(ci_file)
