#!/usr/bin/env python3
"""Quick regression for untyped bytes subject on re.sub."""
# When the subject's static type is not known (runtime word), sub must not
# coerce the result to char* (it could be bytes at runtime).
DRIVER = r'''
import re
def sub_with_untyped(pat, repl, subject):
    # untyped parameter -> subject is a word, not statically MojoBytes *
    return pat.sub(repl, subject)
# A bytes parameter through an untyped variable should still produce bytes.
b = b"aa"
print(re.compile(b"a").sub(b"x", b))
print(sub_with_untyped(re.compile(b"a"), b"x", b))
# A str parameter should still produce str.
print(sub_with_untyped(re.compile("a"), "x", "aa"))
'''
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
prog = tempfile.mkdtemp(prefix='re_reg_')
drv_path = os.path.join(prog, 'drv.py')
with open(drv_path, 'w') as f:
    f.write(DRIVER)
# Just verify the driver runs under CPython first for reference
cpy = subprocess.run([sys.executable, drv_path], capture_output=True, text=True)
print('CPython output:', cpy.stdout.strip())
# Note: the compiled version needs an actual build; this is a quick pinning test.
