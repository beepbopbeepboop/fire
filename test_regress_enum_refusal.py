"""enum.py compiles with run-time class creation landed."""
import os
import sys
import sysconfig

import gimple_codegen


def main():
    path = os.path.join(sysconfig.get_paths()['stdlib'], 'enum.py')
    if not os.path.exists(path):
        print('SKIP  enum compiled: the host Python has no enum.py')
        return 0
    src = open(path).read()
    try:
        gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False, filename=path)
    except RuntimeError as e:
        msg = str(e)
        print('FAIL  enum.py did not compile:\n' + msg[-700:])
        return 1
    print('PASS  enum.py compiles')
    return 0


if __name__ == '__main__':
    sys.exit(main())
