#!/usr/bin/env python3
"""
Fix GIMPLE validation errors for direct string literal assignments.

In GIMPLE, you cannot do: _t4 = "string";
Instead, you must use a global: _slit_N = "string"; then _t4 = _slit_N;

This script:
1. Finds direct string literal assignments
2. Creates global declarations for them in the string pool
3. Replaces assignments to use pool references
"""

import re
import sys
from collections import OrderedDict

def fix_gimple_literals(ci_file):
    with open(ci_file, 'r') as f:
        content = f.read()

    lines = content.split('\n')

    # Pattern for string literal assignments in code (not declarations)
    # _tX = "string"; but NOT char * _slit_N = "string";
    literal_assign_pattern = r'^(\s+)(_t\d+)\s+=\s+("(?:[^"\\]|\\.)*");'

    # Track which strings are already in the pool
    existing_pool = {}
    slit_counter = 0

    # First pass: find existing _slit_ definitions to know the counter
    for line in lines:
        if line.startswith('char * _slit_'):
            match = re.match(r'char \* (_slit_(\d+)) = ("(?:[^"\\]|\\.)*");', line)
            if match:
                slit_name = match.group(1)
                slit_num = int(match.group(2))
                slit_value = match.group(3)
                existing_pool[slit_value] = slit_name
                slit_counter = max(slit_counter, slit_num + 1)

    # Second pass: find and fix direct literal assignments
    new_pool_entries = []
    output_lines = []
    literal_to_slit = {}

    for line in lines:
        match = re.match(literal_assign_pattern, line)
        if match:
            indent = match.group(1)
            var_name = match.group(2)
            literal_value = match.group(3)

            # Check if we already have this in the pool
            if literal_value in existing_pool:
                slit_name = existing_pool[literal_value]
            elif literal_value in literal_to_slit:
                slit_name = literal_to_slit[literal_value]
            else:
                # Create a new pool entry for this literal
                slit_name = f'_slit_{slit_counter}'
                slit_counter += 1
                literal_to_slit[literal_value] = slit_name
                new_pool_entries.append(f'char * {slit_name} = {literal_value};')

            # Replace the direct assignment with a pool reference
            output_lines.append(f'{indent}{var_name} = {slit_name};')
        else:
            output_lines.append(line)

    # Insert new pool entries after existing pool definitions
    final_lines = []
    pool_inserted = False

    for i, line in enumerate(output_lines):
        final_lines.append(line)

        # After the last char * _slit_ definition, insert new pool entries
        if not pool_inserted and line.startswith('char * _slit_'):
            # Check if next line is NOT a pool definition
            if i + 1 < len(output_lines) and not output_lines[i + 1].startswith('char * _slit_'):
                final_lines.extend(new_pool_entries)
                pool_inserted = True

    # If we never found existing pool definitions, insert at the top after includes
    if not pool_inserted and new_pool_entries:
        # Find where to insert (after includes and early declarations)
        insert_pos = 0
        for i, line in enumerate(final_lines):
            if line.startswith('#include') or line.startswith('extern ') or \
               line.startswith('void mojo_print') or line.startswith('char *gimple'):
                insert_pos = i + 1
        final_lines[insert_pos:insert_pos] = new_pool_entries

    # Write the fixed output
    with open(ci_file, 'w') as f:
        f.write('\n'.join(final_lines))

    print(f"✓ Fixed GIMPLE literal assignments in {ci_file}")
    print(f"  Created {len(literal_to_slit)} new pool entries")
    print(f"  Fixed {len([l for l in lines if re.match(literal_assign_pattern, l)])} direct assignments")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    fix_gimple_literals(ci_file)
