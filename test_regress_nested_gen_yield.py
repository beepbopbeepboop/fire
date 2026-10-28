#!/usr/bin/env python3
"""Regression for bug CODEGEN_nested_generator_yield_type_and_delegation: a nested
generator that yields a literal AND re-yields another generator's loop-bound
value must type the loop-bound value from the delegate's value_ctype, not
default to int64_t."""
import subprocess, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')

def build(src_path):
    return subprocess.run([sys.executable, MOJO, 'build', src_path],
                          capture_output=True, text=True)

TEST_SRC = '''
def _rows(items):
    for line in items:
        yield line

def build_section(name):
    def render():
        yield ''
        for line in _rows(['a', 'b']):
            yield line
    return render

def main():
    for x in build_section("test")():
        print(x)
main()
'''

tmp = os.path.join(HERE, '.tmp', 'regress_nested_gen.py')
os.makedirs(os.path.dirname(tmp) or '.', exist_ok=True)
with open(tmp, 'w') as f:
    f.write(TEST_SRC)

r = build(tmp)
# Before fix: refusal naming yield-type disagreement; after fix: builds
if r.returncode != 0 or 'every `yield` must carry a value' in (r.stderr or ''):
    print('FAIL: nested generator yield type still broken')
    print('stderr snippet:', (r.stderr or '')[-300:])
    sys.exit(1)
else:
    print('PASS: nested generator yield type fixed')
    sys.exit(0)
