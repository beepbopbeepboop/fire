"""Test that import statements generate extern declarations correctly."""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

# Test 1: Verify extern declarations are generated for imports
test_code = """\
from test_helper import double, add

def main() -> Int:
    var x: Int = 10
    return x
"""

print("Testing import code generation...")
c_code = compile_to_gimple(test_code)

# Check for extern declarations with parameter types
# Note: "double" is a C keyword, so it becomes "mojo_double"
if 'extern int mojo_double (int x);' in c_code or 'extern int double (int x);' in c_code:
    print("✓ extern declaration for 'double' with parameters found")
else:
    print("✗ extern declaration for 'double' with parameters NOT found")
    print("\nGenerated code:")
    print(c_code[:1000])
    sys.exit(1)

if 'extern int add (int x, int y);' in c_code:
    print("✓ extern declaration for 'add' with parameters found")
else:
    print("✗ extern declaration for 'add' with parameters NOT found")
    print("\nGenerated code snippet:")
    for line in c_code.split('\n'):
        if 'extern' in line and ('add' in line or 'double' in line):
            print(line)
    sys.exit(1)

# Check that imports are no longer in TODOs
if '/* TODO: import' in c_code:
    print("✗ Found old TODO comment for imports")
    sys.exit(1)
else:
    print("✓ No TODO comments for imports")

# Verify it's valid GIMPLE syntax (check for required headers)
if '#include <stdint.h>' in c_code and '#include "mojo_runtime.h"' in c_code:
    print("✓ Required headers present")
else:
    print("✗ Missing required headers")
    sys.exit(1)

print("\nAll import code generation tests passed!")
print("\nGenerated C code snippet:")
print("-" * 60)
# Print first part with externs
lines = c_code.split('\n')
for i, line in enumerate(lines[:50]):
    if 'extern' in line or '#include' in line or 'Generated' in line:
        print(line)
