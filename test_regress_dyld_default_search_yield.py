#!/usr/bin/env python3
"""Regression test for bug-compile-fail-ctypes-macholib-dyld.

Lib/ctypes/macholib/dyld.py's `dyld_default_search(name, env=None)` is a
generator whose only in-module caller is `dyld_find`, which passes its own
`name: str`. The call-site scan records `name` as 'p' (the unanimous kind of
the arguments passed for it), and coro's yield-slot check uses that kind, so
the yields (`name`, `os.path.join(...)`) agree on char *. But the C signature
built by funcs_shared._param_ctype ignored the registry and declared `name`
as the generic int64_t box, so the production yield-type check saw
`declared['name'] == 'int64_t'` against char * joins and refused the whole
module. The fix makes the signature consult the same registry.

Self-contained (no external stdlib path). The `dyld_find('x')` call in main
is what makes the call-site kind for `dyld_find`'s own `name` a literal 'p',
so it is the unanimous contract the compiled path is allowed to trust.
"""
import sys
sys.path.insert(0, '.')
import gimple_codegen

SRC = '''\
import os

def framework_info(filename):
    if filename.startswith('/') is False:
        return None
    return {'location': filename.split('/')[0], 'name': filename}

def dyld_fallback_library_path(env=None):
    return ['/usr/lib']

def dyld_default_search(name, env=None):
    yield name

    framework = framework_info(name)

    fallback_library_path = dyld_fallback_library_path(env)
    for path in fallback_library_path:
        yield os.path.join(path, os.path.basename(name))

def dyld_find(name: str, env=None):
    for path in dyld_default_search(name, env):
        return path
    raise ValueError("dylib %s could not be found" % (name,))

def main():
    print(dyld_find('x'))

main()
'''

c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
    SRC, do_imports=False, filename='dyld_repro.py')

# Before the fix: compile_to_gimple_with_cpp raised RuntimeError ("cannot
# compile module: ... dyld_default_search ... yields ... agree") and the
# module fell back to source. After: the generator is a coroutine whose
# name parameter is char *, matching its yields.
if '_impl (char * name' not in cpp_code:
    print('FAIL: dyld_default_search name param is not char *')
    sys.exit(1)
print('PASS: dyld_default_search compiles as a coroutine with char * name')
sys.exit(0)
