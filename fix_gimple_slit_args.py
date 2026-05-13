#!/usr/bin/env python3
"""
Fix GIMPLE validation errors for passing string literals to functions.

In GIMPLE, function arguments must be SSA values (temporaries), not global
declarations. This script finds calls like:
    _tN = func(..., _slit_M, ...)
And transforms them to:
    _t_tmp = _slit_M;
    _tN = func(..., _t_tmp, ...)
"""

import re
import sys

def fix_gimple_slit_args(ci_file):
    with open(ci_file, 'r') as f:
        lines = f.readlines()

    # Patterns
    call_pattern = r'^(\s*)(_t\d+)\s*=\s*(\w+)\s*\((.*_slit_\d+.*)\);'
    slit_ref_pattern = r'_slit_\d+'
    func_pattern = r'^[a-z_].*\s+(\w+)\s*\('
    bb_label_pattern = r'^\s*bb_\d+:\s*$'

    # First pass: create mapping of all _slit_ to temporaries and
    # track which slit refs are used in each function
    all_slit_refs = set()
    func_slit_needs = {}  # func_name -> set of _slit_ that need temps
    slit_to_temp = {}  # _slit_N -> _t_slit_M

    current_func = None
    for i, line in enumerate(lines):
        # Check if this is a function definition
        func_match = re.match(func_pattern, line)
        if func_match:
            current_func = func_match.group(1)
            if current_func not in func_slit_needs:
                func_slit_needs[current_func] = set()
            continue

        # Track slit refs used in this function
        if current_func:
            slit_refs = re.findall(slit_ref_pattern, line)
            all_slit_refs.update(slit_refs)
            # If this is a function call, mark slits as needing temps
            if re.match(call_pattern, line):
                func_slit_needs[current_func].update(slit_refs)

    # Create mapping of _slit_ to temporaries (once for all)
    temp_counter = 1000
    for slit_ref in sorted(all_slit_refs):
        temp_var = f'_t_slit_{temp_counter}'
        slit_to_temp[slit_ref] = temp_var
        temp_counter += 1

    # Second pass: process and rebuild file
    output_lines = []
    current_func = None
    decls_inserted = {}  # func_name -> True if we've inserted decls

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this is a function definition
        func_match = re.match(func_pattern, line)
        if func_match:
            current_func = func_match.group(1)
            decls_inserted[current_func] = False
            output_lines.append(line)
            i += 1
            continue

        # If in a function and we haven't inserted decls yet
        if current_func and not decls_inserted.get(current_func):
            # Check if this is a bb_ label
            if re.match(bb_label_pattern, line):
                # Insert declarations for slit refs needed by this function
                slit_refs_needed = func_slit_needs.get(current_func, set())
                for slit_ref in sorted(slit_refs_needed):
                    temp_var = slit_to_temp[slit_ref]
                    output_lines.append(f'  char * {temp_var};\n')
                decls_inserted[current_func] = True
                output_lines.append(line)
                i += 1
                continue
            # If this is not a variable declaration or opening brace
            elif not re.match(r'\s*(char|int|int64_t|void|_Bool|double)\s+', line) and \
                 not re.match(r'^\s*\{\s*$', line) and \
                 not re.match(r'^\s*$', line):
                # End of declarations - insert before this line
                slit_refs_needed = func_slit_needs.get(current_func, set())
                if slit_refs_needed:
                    for slit_ref in sorted(slit_refs_needed):
                        temp_var = slit_to_temp[slit_ref]
                        output_lines.append(f'  char * {temp_var};\n')
                decls_inserted[current_func] = True
                output_lines.append(line)
                i += 1
                continue

        # Process function calls - replace _slit_ with temporaries
        call_match = re.match(call_pattern, line)
        if call_match:
            indent = call_match.group(1)
            dest_var = call_match.group(2)
            func_name = call_match.group(3)
            args_str = call_match.group(4)

            # Find which _slit_ refs are in this call
            slit_refs = re.findall(slit_ref_pattern, args_str)
            unique_refs = set(slit_refs)

            if unique_refs:
                # Add assignments for each _slit_ ref
                for slit_ref in unique_refs:
                    temp_var = slit_to_temp[slit_ref]
                    output_lines.append(f'{indent}{temp_var} = {slit_ref};\n')

                # Replace _slit_ refs with temporaries in the call
                modified_args = args_str
                for slit_ref in unique_refs:
                    temp_var = slit_to_temp[slit_ref]
                    modified_args = re.sub(r'\b' + re.escape(slit_ref) + r'\b', temp_var, modified_args)

                output_lines.append(f'{indent}{dest_var} = {func_name} ({modified_args});\n')
                i += 1
                continue

        output_lines.append(line)
        i += 1

    # Write the fixed output
    with open(ci_file, 'w') as f:
        f.writelines(output_lines)

    print(f"✓ Fixed GIMPLE string literal arguments in {ci_file}")
    print(f"  Created {len(slit_to_temp)} temporary variables for string literals")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    fix_gimple_slit_args(ci_file)
