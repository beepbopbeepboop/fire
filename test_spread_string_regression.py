#!/usr/bin/env python3
"""Regression for CODEGEN_a_star_spread_of_a_string_beside_its_own_slots.
A *str spread beside a literal int slot must not print that slot's int zero as None."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_gimple_runner import compile_mojo_to_gimple_exe, run_executable_stdout as run_exe

SRC = '''
def tup_str(a: str) -> tuple:
    return (0, *a)

def list_str(a: str) -> list:
    return [0, *a]

print(tup_str('ab'))
print(list_str('ab'))
print([*'ab'])
'''

exe = compile_mojo_to_gimple_exe(SRC)
stdout = run_exe(exe)
assert "(0, 'a', 'b')" in stdout or "(0, 'a', 'b')" in stdout.replace(' ', ''), f"tuple wrong: {stdout!r}"
assert "[0, 'a', 'b']" in stdout or "[0, 'a', 'b']" in stdout.replace(' ', ''), f"list wrong: {stdout!r}"
assert "['a', 'b']" in stdout, f"plain spread wrong: {stdout!r}"
# The critical assertion: must NOT contain None where 0 should be
assert "None" not in stdout, f"int zero misprinted as None: {stdout!r}"
print("PASS regression:", stdout.strip())
