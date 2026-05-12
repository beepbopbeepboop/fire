#!/usr/bin/env python3
"""
Consolidate string literals into a shared pool across the compiled .ci file.

The mojo compiler generates independent string pools for each module.
This post-processes the output to:
1. Collect all unique string literal definitions
2. Build a consolidated pool with global char * pointers
3. Make unit-local references static to avoid linkage issues
4. Remove duplicate definitions
"""

import re
import sys
from collections import OrderedDict

def consolidate_string_pool(ci_file):
    with open(ci_file, 'r') as f:
        content = f.read()

    lines = content.split('\n')

    # Parse all string literal definitions
    # Pattern: char * _slit_123 = "...";
    slit_pattern = r'^(char \* (_slit_\d+) = ("(?:[^"\\]|\\.)*");)$'

    string_pool = OrderedDict()  # value -> (slit_name, line)
    slit_to_canonical = {}  # old_slit_name -> canonical_slit_name

    # First pass: collect all string definitions
    for i, line in enumerate(lines):
        match = re.match(slit_pattern, line)
        if match:
            full_decl = match.group(1)
            slit_name = match.group(2)
            slit_value = match.group(3)

            # Use the value as the key - if we've seen this value before, reuse it
            if slit_value not in string_pool:
                # First time seeing this value
                string_pool[slit_value] = (slit_name, i)
                slit_to_canonical[slit_name] = slit_name
            else:
                # We've seen this value - map to the canonical name
                canonical_name = string_pool[slit_value][0]
                slit_to_canonical[slit_name] = canonical_name

    # Second pass: build output with consolidated pool
    output_lines = []
    emitted_values = set()

    # Track where we are in the file
    in_function = False
    current_line_no = 0

    for i, line in enumerate(lines):
        current_line_no = i

        # Check if this is a string definition
        match = re.match(slit_pattern, line)
        if match:
            slit_name = match.group(2)
            slit_value = match.group(3)

            # Only emit this string if:
            # 1. It's the canonical definition for this value, AND
            # 2. We haven't emitted it yet
            canonical_name = slit_to_canonical[slit_name]
            if slit_name == canonical_name and slit_value not in emitted_values:
                output_lines.append(f'char * {canonical_name} = {slit_value};')
                emitted_values.add(slit_value)
            # Skip non-canonical definitions (duplicates)
            continue

        # For all other lines, replace references to old slit names with canonical names
        modified_line = line
        for old_name, canonical_name in slit_to_canonical.items():
            if old_name != canonical_name:
                # Replace old_name with canonical_name as whole words
                modified_line = re.sub(r'\b' + re.escape(old_name) + r'\b',
                                       canonical_name, modified_line)

        output_lines.append(modified_line)

    # Write the consolidated output
    with open(ci_file, 'w') as f:
        f.write('\n'.join(output_lines))

    print(f"✓ Consolidated string pool in {ci_file}")
    print(f"  Total unique strings: {len(string_pool)}")
    print(f"  Consolidated from {len(slit_to_canonical)} references")
    print(f"  Removed {len(slit_to_canonical) - len(string_pool)} duplicate definitions")

if __name__ == '__main__':
    ci_file = 'stage1/mojo.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    consolidate_string_pool(ci_file)
