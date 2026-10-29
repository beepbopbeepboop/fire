# Quick regression for CODEGEN_module_boundary_carries_no_value_types
# Shape 1: module-qualified call to unannotated free function.
# Before fix: parameter typed int64_t, len() reads list header.
# After fix: observations collected, parameter types as char*.

import os, sys
sys.path.insert(0, '.')
from gimple_codegen import compile_to_gimple

m_py = '''
def f(s):
    return len(s)
'''

u_py = '''
import m
def main():
    print(m.f('abcd'))
main()
'''

with open('.tmp/m_reg.py','w') as f: f.write(m_py)
with open('.tmp/u_reg.py','w') as f: f.write(u_py)

# Just verify compilation succeeds and emitted C declares f(char*) not int64_t.
code = compile_to_gimple(u_py, do_imports=True, filename='.tmp/u_reg.py')
# Look for the imported module's function emission.
# Since the exact mangled name varies, just check the emitted C contains
# 'char * s' or similar near the function definition/declaration.
# We will inspect the output manually.
# Debug: did the module-qualified call get recognized?
# We can check by temporarily looking at _scalar_obs if we had access.
print('COMPILED OK; checking emitted parameter type...')
# If the fix reached the observation, we expect no int64_t s for f.
# If it didn't, int64_t s will appear.
has_int_s = 'int64_t s' in code
print('has int64_t s:', has_int_s)
print('FIRST 1200 chars of code:')
print(code[:1200])
