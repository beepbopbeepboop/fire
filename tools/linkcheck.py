#!/usr/bin/env python3
"""Compile ONE stdlib .mojo module to C, build its object, and report every
symbol the object still needs but does not define.

    python3 tools/linkcheck.py test/itertools/test_count.mojo [--run]

This is the acceptance instrument the bug docs refer to when they say a file
must be verified by LINKING it and checking for undefined symbols.
`compile_stdlib.py` is `gcc -fgimple -fsyntax-only` and never links, and
`tools/undef_import_census.py` counts call sites in generated C — neither can
see that a call names a symbol no object defines.

What it links against, and why that is stated rather than assumed:
  * `runtime/fire_runtime.c` — the C runtime every generated TU calls into.
  * the CAS/dylib objects for the module's own stdlib imports, when they exist
    (`build/libmojostdlib.arm64.dylib`).
Anything still undefined after that is reported by name. A symbol the module's
OWN object should define (its structs' `__next__`, its in-TU instantiations)
appearing in that list is the failure this exists to catch.

LIMITATION, stated because it is easy to over-read a green result: this
compiles ONE module. Two consequences, both real:
  * the `std.testing` `assert_equal`/`assert_raises` helpers are STUBBED in the
    resulting link, so a file's internal assertions are NOT observed to pass;
  * a `TestSuite.discover_tests[__functions_in_module()]` file's own test
    functions are reached only by NAME through std.testing's dispatch, which
    this link does not provide, so `--run` links and runs a trivial `main`
    rather than the file's tests.
What IS verified: the module's object defines what it must, nothing it needs
is missing, and (with --run) the program links and completes.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from build_config import find_gcc  # noqa: E402
from build_stdlib_dylib import compile_module_to_c  # noqa: E402
from module_loader import STDLIB_PATH, module_name_for_path  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('relpath')
    ap.add_argument('--run', action='store_true',
                    help='also link an executable and run it')
    ap.add_argument('--keep', action='store_true')
    args = ap.parse_args()

    src_path = os.path.join(STDLIB_PATH, args.relpath)
    name = module_name_for_path(src_path)
    work = os.path.join(ROOT, 'build', 'linkcheck')
    os.makedirs(work, exist_ok=True)

    try:
        c_src = compile_module_to_c(open(src_path).read(), src_path, name)
    except Exception as e:
        # Codegen REFUSED the module. That is a legitimate state (the
        # `next(<user-defined iterator struct>)` refusal is deliberate), and it
        # is strictly better than a syntax check: report it and stop, rather
        # than letting a traceback imply the tool broke.
        print(f'codegen REFUSED {args.relpath}:')
        print('  ' + str(e).split('.')[0].strip())
        return 2
    cfile = os.path.join(work, name + '.c')
    ofile = os.path.join(work, name + '.o')
    with open(cfile, 'w') as f:
        f.write(c_src)
    print(f'C   -> {cfile} ({len(c_src)} bytes)')

    gcc = find_gcc()
    # `-fgimple` is REQUIRED, not optional: every function this codegen emits
    # is declared `int64_t __GIMPLE f(...)`, and plain `gcc -c` rejects that
    # with "error: '__GIMPLE' only valid with '-fgimple'" — so a link check
    # built without it measures nothing. These are the same flags
    # `build_stdlib_dylib._OBJ_FLAGS` uses for a real module object, so the
    # symbol set measured here is the symbol set the dylib build produces.
    objflags = ['-fgimple', '-fPIC', '-D__MOJO_STDLIB_MODE__',
                '-I' + os.path.join(ROOT, 'runtime')]
    rc = subprocess.run([gcc, *objflags, '-c', '-o', ofile, cfile],
                        capture_output=True, text=True)
    if rc.returncode != 0:
        print('gcc -c FAILED')
        for l in rc.stderr.splitlines():
            if ': error:' in l:
                print('  ' + l)
        return 1
    print(f'obj -> {ofile}')

    nm = subprocess.run(['nm', '-g', ofile], capture_output=True, text=True).stdout
    defined, undef = set(), set()
    for line in nm.splitlines():
        parts = line.split()
        if len(parts) == 3:
            kind, _, sym = parts
            (undef if kind == 'U' else defined).add(sym)
        elif len(parts) == 2 and parts[0] in 'UTRDB':
            (undef if parts[0] == 'U' else defined).add(parts[1])

    dylib = os.path.join(ROOT, 'build', 'libmojostdlib.arm64.dylib')
    lib_syms = set()
    if os.path.exists(dylib):
        out = subprocess.run(['nm', '-gU', dylib], capture_output=True, text=True).stdout
        for line in out.splitlines():
            p = line.split()
            if p:
                lib_syms.add(p[-1])
    print(f'dylib: {len(lib_syms)} exported symbols'
          f'{" (absent)" if not lib_syms else ""}')

    runtime_c = os.path.join(ROOT, 'runtime', 'fire_runtime.c')
    rt_obj = os.path.join(work, 'fire_runtime.o')
    if not os.path.exists(rt_obj):
        rc = subprocess.run([gcc, *objflags, '-c', '-o', rt_obj, runtime_c],
                            capture_output=True, text=True)
        if rc.returncode != 0:
            print('runtime build failed:', rc.stderr.splitlines()[:3])

    still = sorted(s for s in undef
                   if s not in defined and s not in lib_syms
                   and not s.startswith(('mojo_', '_mojo', 'printf', 'malloc',
                                         'free', 'memcpy', 'memset', 'sprintf',
                                         'snprintf', 'str', 'gcc_', 'dlsym',
                                         'dl', '__')))

    print(f'\nundefined after runtime + dylib: {len(still)}')
    for s in still:
        print('  U ' + s)

    if args.run:
        # The `std.testing` assertion helpers this one-module link cannot
        # supply, stubbed WEAK so the link completes — and so a REAL definition
        # appearing later would win over the stub rather than being silently
        # shadowed by it. This is exactly the setup the three 2026-10-03
        # removals were verified under, and it is why a green `--run` here
        # does NOT mean the file's assertions passed.
        stubs_c = os.path.join(work, name + '_stubs.c')
        stub_syms = [s for s in still
                     if s.startswith(('_std_', '_test_', '_runtime_'))
                     and 'assert' in s]
        with open(stubs_c, 'w') as f:
            f.write('#include <stdint.h>\n')
            for s in stub_syms:
                # `nm` prints Mach-O symbols WITH the platform's leading
                # underscore, so a name taken from `nm -u` must have exactly
                # one stripped before it goes back into C source — otherwise
                # the stub is defined as `__sym` and the reference to `_sym`
                # stays unresolved, which is what this first produced.
                csym = s[1:] if s.startswith('_') else s
                f.write(f'__attribute__((weak)) int64_t {csym}(void) '
                        f'{{ return 0; }}\n')
        if stub_syms:
            print(f'stubbed (weak, so a real definition would win): '
                  f'{", ".join(stub_syms)}')
        stub_o = os.path.join(work, name + '_stubs.o')
        subprocess.run([gcc, '-c', '-o', stub_o, stubs_c], check=True)

        # `compile_module_to_c` runs `gen_module(emit_entry_points=False)`, so
        # the emitted TU has no `main`. Supply a trivial one: the point of this
        # mode is to prove the object LINKS and the program COMPLETES, not to
        # run the file's test functions (see the limitation above).
        main_c = os.path.join(work, name + '_main.c')
        with open(main_c, 'w') as f:
            f.write('int main(void) { return 0; }\n')
        main_o = os.path.join(work, name + '_main.o')
        subprocess.run([gcc, *objflags, '-c', '-o', main_o, main_c], check=True)
        exe = os.path.join(work, name + '.bin')
        link = [gcc, '-o', exe, ofile, main_o, rt_obj, stub_o, '-lm']
        if os.path.exists(dylib):
            link += [dylib, '-Wl,-rpath,' + os.path.dirname(dylib)]
        lr = subprocess.run(link, capture_output=True, text=True)
        if lr.returncode != 0:
            print('\nLINK FAILED')
            # Only the `"_sym", referenced from:` lines, NOT the indented
            # continuation lines (which also start with `_` and name the
            # CALLING function, not the missing symbol) — printing those
            # reports a module's own defined functions as undefined.
            for l in lr.stderr.splitlines():
                if l.strip().startswith('"_') and 'referenced from' in l:
                    print('  ' + l.strip())
                elif 'Undefined symbols' in l or l.strip().startswith('ld:'):
                    print('  ' + l.strip())
            return 1
        print(f'\nlinked -> {exe}')
        rr = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        print(f'run exit={rr.returncode}')
        if rr.stdout:
            print('stdout:', rr.stdout[:400])
        if rr.stderr:
            print('stderr:', rr.stderr[:400])

    if not args.keep:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
