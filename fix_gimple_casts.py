#!/usr/bin/env python3
"""
Fix GIMPLE validation errors for cast expressions in function arguments.

In GIMPLE, you cannot do: func(arg, (type)var);
Instead, you must use a temporary: _tN = (type)var; func(arg, _tN);

This script finds and extracts casts from function arguments.
"""

import re
import sys

def fix_gimple_casts(ci_file):
    with open(ci_file, 'r') as f:
        lines = f.readlines()

    output_lines = []
    cast_count = 0
    next_temp_num = 1

    for i, line in enumerate(lines):
        # Look for patterns like: func(..., (type)varname, ...);
        # Pattern: (cast)varname where it's inside a function call
        modified_line = line

        # Find all cast expressions and extract them
        while True:
            # Pattern: (typename)varname inside function call parens
            match = re.search(r',\s*\((\w+(?:\s*\*)?)\)(\w+)\s*([,\)])', modified_line)
            if not match:
                break

            cast_type = match.group(1)
            var_name = match.group(2)
            after = match.group(3)
            cast_count += 1

            # Create a temporary variable
            temp_var = f'_gimple_cast_{next_temp_num}'
            next_temp_num += 1

            # Insert the cast assignment before the current line
            indent = len(line) - len(line.lstrip())
            output_lines.append(' ' * indent + f'{temp_var} = ({cast_type}){var_name};\n')

            # Replace the cast expression with just the temp var
            before = modified_line[:match.start(1) - 1]  # Before the (
            rest = f', {temp_var}{after}' + modified_line[match.end(3):]
            modified_line = before + rest

        output_lines.append(modified_line)

    # Write the fixed output
    with open(ci_file, 'w') as f:
        f.writelines(output_lines)

    print(f"✓ Fixed GIMPLE cast expressions in {ci_file}")
    print(f"  Extracted {cast_count} casts to temporary assignments")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    fix_gimple_casts(ci_file)
