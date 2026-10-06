"""Test that import statements generate extern declarations correctly."""
import re
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

# Check for extern declarations with parameter types.
# Note: "double" is a C keyword, so it becomes "mojo_double". Every
# mangleable free function (a local def or an imported Mojo function with a
# resolved signature) also gets a 6-hex-digit overload-hash suffix appended
# to its C symbol (gimple_codegen.py's _func_csym/overload_suffix_for) so
# that two same-named functions with different signatures can't collide,
# and (per a later module-qualification change) may additionally be
# prefixed with its defining module's name — so the C symbol looks like
# "[<module>_]mojo_double_<hash>", not bare "mojo_double". And `Int` is
# this codegen's boxed machine word, which maps to `int64_t` (ABI.md), not
# plain C `int` — an old/stale convention this test used to assert that
# has since been corrected everywhere else in the codegen (see
# gimple_codegen.py's _TYPE_MAP and module_loader.py's _mojo_type_to_c,
# which must both agree or the extern declaration's mangled name won't even
# match the symbol the defining module actually emits).
if re.search(r'extern int64_t (\w+_)?mojo_double_[0-9a-f]{6} \(int64_t x\);', c_code):
    print("✓ extern declaration for 'double' with parameters found")
else:
    print("✗ extern declaration for 'double' with parameters NOT found")
    print("\nGenerated code:")
    print(c_code[:1000])
    sys.exit(1)

if re.search(r'extern int64_t (\w+_)?add_[0-9a-f]{6} \(int64_t x, int64_t y\);', c_code):
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

# Verify it's valid GIMPLE syntax (check for required headers).
# gimple_codegen.py emits fire_runtime.h as an angle-bracket system include
# (relying on -I<runtime dir>), not a quoted local include — this test used
# to assert the quoted form, which was never actually emitted.
if '#include <stdint.h>' in c_code and '#include <fire_runtime.h>' in c_code:
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
