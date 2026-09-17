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

    value_to_canonical = {}  # string value -> canonical_slit_name
    slit_id_to_entries = {}  # slit_id (e.g., 10040) -> list of (slit_name, slit_value, line_idx)
    slit_to_canonical = {}  # old_slit_name -> canonical_slit_name

    # First pass: collect all string definitions and detect conflicts
    for i, line in enumerate(lines):
        match = re.match(slit_pattern, line)
        if match:
            full_decl = match.group(1)
            slit_name = match.group(2)
            slit_value = match.group(3)

            # Extract the numeric ID
            slit_id = int(slit_name.split('_')[2])

            # Track entries by ID to detect conflicts
            if slit_id not in slit_id_to_entries:
                slit_id_to_entries[slit_id] = []
            slit_id_to_entries[slit_id].append((slit_name, slit_value, i))

    # Resolve conflicts: for each ID, if there are multiple entries with different values,
    # rename the later ones to new unique IDs
    next_new_id = 20000  # Use a different range for renamed entries
    rename_map = {}  # old_slit_name -> new_slit_name

    for slit_id in sorted(slit_id_to_entries.keys()):
        entries = slit_id_to_entries[slit_id]
        if len(entries) > 1:
            # Multiple entries with same ID - check if they have different values
            values_seen = {}
            for slit_name, slit_value, line_idx in entries:
                if slit_value not in values_seen:
                    values_seen[slit_value] = slit_name
                else:
                    # Same value with same ID - will be handled by consolidation
                    pass

            if len(values_seen) > 1:
                # Conflict! Different values for same ID. Rename later occurrences.
                canonical_name = None
                for slit_name, slit_value, line_idx in entries:
                    if canonical_name is None:
                        canonical_name = slit_name
                    else:
                        # Rename this one
                        new_name = f'_slit_{next_new_id}'
                        rename_map[slit_name] = new_name
                        next_new_id += 1

    # Second pass: build consolidated pool mapping
    for i, line in enumerate(lines):
        match = re.match(slit_pattern, line)
        if match:
            slit_name = match.group(2)
            slit_value = match.group(3)

            # Apply any renames first
            canonical_name = rename_map.get(slit_name, slit_name)

            # Then check if this value already has a canonical name
            if slit_value not in value_to_canonical:
                value_to_canonical[slit_value] = canonical_name
                slit_to_canonical[slit_name] = canonical_name
            else:
                # Consolidate to existing name
                slit_to_canonical[slit_name] = value_to_canonical[slit_value]

    # Third pass: build output with consolidated pool
    output_lines = []
    emitted_values = set()
    emitted_names = set()

    for i, line in enumerate(lines):
        # Check if this is a string definition
        match = re.match(slit_pattern, line)
        if match:
            slit_name = match.group(2)
            slit_value = match.group(3)

            # Apply rename if needed
            if slit_name in rename_map:
                slit_name = rename_map[slit_name]

            # Get the canonical name for this value
            canonical_name = slit_to_canonical.get(slit_name, slit_name)

            # Only emit if:
            # 1. It's the canonical definition for this value, AND
            # 2. We haven't emitted it yet
            if slit_name == canonical_name and canonical_name not in emitted_names:
                output_lines.append(f'char * {canonical_name} = {slit_value};')
                emitted_names.add(canonical_name)
            # Skip non-canonical definitions (duplicates)
            continue

        # For all other lines, replace references to old slit names with canonical names
        modified_line = line
        for old_name, canonical_name in slit_to_canonical.items():
            if old_name != canonical_name:
                # Replace old_name with canonical_name as whole words
                modified_line = re.sub(r'\b' + re.escape(old_name) + r'\b',
                                       canonical_name, modified_line)

        # Also apply the rename map
        for old_name, new_name in rename_map.items():
            if old_name != new_name:
                modified_line = re.sub(r'\b' + re.escape(old_name) + r'\b',
                                       new_name, modified_line)

        output_lines.append(modified_line)

    # Write the consolidated output
    with open(ci_file, 'w') as f:
        f.write('\n'.join(output_lines))

    unique_canonical = len(value_to_canonical)
    print(f"✓ Consolidated string pool in {ci_file}")
    print(f"  Total unique strings: {unique_canonical}")
    print(f"  Consolidated from {len(slit_to_canonical)} references")
    print(f"  Removed {len(slit_to_canonical) - unique_canonical} duplicate definitions")
    if rename_map:
        print(f"  Renamed {len(rename_map)} conflicting IDs")

if __name__ == '__main__':
    ci_file = 'stage1/fire.ci'
    if len(sys.argv) > 1:
        ci_file = sys.argv[1]
    consolidate_string_pool(ci_file)
