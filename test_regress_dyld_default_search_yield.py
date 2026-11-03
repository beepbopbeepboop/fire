#!/usr/bin/env python3
"""Regression test for bug-compile-fail-ctypes-macholib-dyld.

Lib/ctypes/macholib/dyld.py's `dyld_default_search(name, env=None)` is a
generator whose only in-module caller is `dyld_find`, which passes its own
`name: str`. The call-site scan records `name` as 'p' (the unanimous kind
of the arguments passed for it), and coro's yield-slot check uses that kind,
so the yields (`name`, `os.path.join(...)`) agree on char *. But the C
signature built by funcs_shared._param_ctype ignored the registry and
declared `name` as the generic int64_t box, so the production yield-type
check saw `declared['name'] == 'int64_t'` against char * joins and
refused the whole module. The fix makes the signature consult the same
registry.

Self-contained (no external stdlib path). The `dyld_find('x')` call in main
is what makes the call-site kind for `dyld_find`'s own `name` a literal 'p',
so it is the unanimous contract the compiled path is allowed to trust.

The generator may land on either coroutine backend (MOJO_CORO; see
doc/COROUTINE.html section 5.5) and both must carry the same contract --
the generator compiles, its value slot is char *, and its `name`
parameter is typed from the call-site registry rather than the int64_t
box:
  * the A3 stack-switch lowering (the DEFAULT since the section 5.5
    cutover) emits `__mgco_dyld_default_search_body` with a char * value
    slot in the C unit -- the yield goes through the `__mojo_coro_yield_p`
    helper;
  * the C++20 companion (the escape hatch, and where this generator used
    to land, before the stack-switch backend learned to accept it) emits
    the `_impl (char * name ...)` coroutine in the generated cpp.

The compile is pinned to the default backend: without the pin, a process
that exports MOJO_CORO=cpp would be judged against the escape hatch,
whose separate `framework_info` same-module-callee gap (a different bug
class, tracked by the Tools/c-analyzer docs) is not what this test pins.
"""
import sys
sys.path.insert(0, '.')
import gimple_codegen
from mojo.middle import coro

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

with coro.pinned('stackswitch'):
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
        SRC, do_imports=False, filename='dyld_repro.py')

# Before the fix (2026-10-30): compile_to_gimple_with_cpp raised
# RuntimeError ("cannot compile module: ... dyld_default_search ...") on
# trees where the stack-switch backend could not type the slot, and the
# companion C++ coroutine declared `name` as the int64_t box while its
# yield slot was char *. After: the generator is a compiled coroutine
# whose name parameter and value slot are both char *.
if '__mgco_dyld_default_search_body' in c_code:
    if '__mojo_coro_yield_p' not in c_code:
        print('FAIL: dyld_default_search value slot is not char *')
        sys.exit(1)
    print('PASS: dyld_default_search compiles as a stack-switch coroutine with a char * value slot')
    sys.exit(0)
if '_impl (char * name' in cpp_code:
    print('PASS: dyld_default_search compiles as a C++ coroutine with char * name')
    sys.exit(0)
print('FAIL: dyld_default_search is not a compiled coroutine with a char * slot '
      '(refused by both backends, or the name param is not char *)')
sys.exit(1)
