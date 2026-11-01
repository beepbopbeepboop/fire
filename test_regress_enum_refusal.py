"""Pins the honest state of `enum.py` after its generators were fixed.

Every generator of CPython's `Lib/enum.py` (`Flag._iter_member_`, `_iter_member_by_value_`,
`_iter_member_by_def_`, for `Flag` and `IntFlag`) now compiles. The module must STILL be refused
as a whole - it builds its classes with the 3-argument `type(name, bases, namespace)` at run
time, which the compiled path does not model yet (bugs/CODEGEN_enum_runtime_class_creation.md) -
and the refusal must name THAT, not a generator: compiling `enum` with its metaclass-created
attributes missing would iterate every Flag as empty. When run-time class creation lands this
test is the one to turn around (compile succeeds, program output equals CPython's).
"""
import os
import sys
import sysconfig

import gimple_codegen


def main():
    path = os.path.join(sysconfig.get_paths()['stdlib'], 'enum.py')
    if not os.path.exists(path):
        print('SKIP  enum refusal: the host Python has no enum.py')
        return 0
    src = open(path).read()
    try:
        gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False, filename=path)
    except RuntimeError as e:
        msg = str(e)
        if 'type(name, bases, namespace)' not in msg:
            print('FAIL  enum is refused, but not for run-time class creation:\n' + msg[-700:])
            return 1
        if 'references `cls` in its body' in msg or 'generator function' in msg.split('Unsupported shape')[-1]:
            print('FAIL  a generator of enum.py is refused again:\n' + msg[-700:])
            return 1
        print('PASS  enum.py: generators compile; refused only for run-time class creation')
        return 0
    print('FAIL  enum.py compiled: the metaclass-created attributes are not modelled (silent miscompile?)')
    return 1


if __name__ == '__main__':
    sys.exit(main())
