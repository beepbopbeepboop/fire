#!/usr/bin/env python3
"""Regression test for bug:COMPILE_FAIL_ctypes_macholib_dyld.

The real Lib/ctypes/macholib/dyld.py is a pure library module: no
function in it has a literal call site. Its three generators
(`dyld_default_search`, `dyld_executable_path_search`,
`dyld_override_search`) each yield their UNANNOTATED `name` parameter
beside `os.path.join(...)` yields; `name`'s only in-module caller is the
ordinary `dyld_find`, which forwards its own unannotated `name`, which
`framework_find` forwards from its own unannotated `fn`. The real
callers of `dyld_find`/`framework_find` live in Lib/ctypes/util.py --
another module, never in a single-unit build's closure -- so no
call-site kind exists for any of them.

Before the pointer-evidence machinery (mojo/middle/coro.py's
`_compute_pointer_evidence`, landed 2026-10-31: a parameter its body
uses as a path word -- sliced, `isinstance(p, str|bytes)`-tested, a
str-method receiver, or an argument to `os.path.*` -- or FORWARDED to
another function's path-word parameter, by fixpoint -- resolves an
untypeable call site to a pointer word instead of a refusal), the
static scan read every one of these parameters as a hole and the whole
module was refused (measured on the 2026-10-30 tree, single unit):

    cannot compile module: function(s) dyld_default_search,
    dyld_executable_path_search, dyld_override_search ...
    yields ['name'], whose call sites do not all pass the same
    statically-known type ...

This is the same chain, self-contained (no external stdlib path), with
no module-level call that could anchor a literal kind. It FAILS before
the fix (RuntimeError: cannot compile module ... dyld_default_search
...) and PASSES after: all three generators lower to compiled
coroutine units with a char * value slot, their unannotated parameters
resolved as pointer words.

The compile is pinned to the default (stack-switch) backend, which is
the production path this doc measured: the MOJO_CORO=cpp escape hatch
has a separate, different same-module-callee gap in its generator body
lowering that is not what this test pins.
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

def dyld_env(env, var):
    if env is None:
        env = os.environ
    rval = env.get(var)
    if rval is None:
        return []
    return rval.split(':')

def dyld_framework_path(env=None):
    return dyld_env(env, 'DYLD_FRAMEWORK_PATH')

def dyld_library_path(env=None):
    return dyld_env(env, 'DYLD_LIBRARY_PATH')

def dyld_fallback_framework_path(env=None):
    return dyld_env(env, 'DYLD_FALLBACK_FRAMEWORK_PATH')

def dyld_fallback_library_path(env=None):
    return dyld_env(env, 'DYLD_FALLBACK_LIBRARY_PATH')

def dyld_override_search(name, env=None):
    framework = framework_info(name)
    if framework is not None:
        for path in dyld_framework_path(env):
            yield os.path.join(path, framework['name'])
    for path in dyld_library_path(env):
        yield os.path.join(path, os.path.basename(name))

def dyld_executable_path_search(name, executable_path=None):
    if name.startswith('@executable_path/') and executable_path is not None:
        yield os.path.join(executable_path, name[len('@executable_path/'):])

def dyld_default_search(name, env=None):
    yield name

    framework = framework_info(name)

    if framework is not None:
        fallback_framework_path = dyld_fallback_framework_path(env)
        for path in fallback_framework_path:
            yield os.path.join(path, framework['name'])

    fallback_library_path = dyld_fallback_library_path(env)
    for path in fallback_library_path:
        yield os.path.join(path, os.path.basename(name))

def dyld_find(name, executable_path=None, env=None):
    for path in dyld_default_search(name, env):
        return path
    raise ValueError("dylib %s could not be found" % (name,))

def framework_find(fn, executable_path=None, env=None):
    error = None
    try:
        return dyld_find(fn, executable_path=executable_path, env=env)
    except ValueError as e:
        error = e
    fmwk_index = fn.rfind('.framework')
    if fmwk_index == -1:
        fmwk_index = len(fn)
    fn = os.path.join(fn, os.path.basename(fn[:fmwk_index]))
    try:
        return dyld_find(fn, executable_path=executable_path, env=env)
    except ValueError:
        raise error
    finally:
        error = None
'''

with coro.pinned('stackswitch'):
    try:
        c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
            SRC, do_imports=False, filename='dyld_chain.py')
    except RuntimeError as e:
        print('FAIL: module refused:', str(e)[:400])
        sys.exit(1)

missing = [n for n in ('dyld_default_search', 'dyld_executable_path_search',
                       'dyld_override_search')
           if ('__mgco_%s_body' % n) not in c_code]
if missing:
    print('FAIL: generators not compiled as coroutine units:', missing)
    sys.exit(1)
print('PASS: the unannotated path-word chain compiles all three dyld generators')
sys.exit(0)
