#!/usr/bin/env python3
"""Write the self-host closure's C translation unit to a file, exactly as
`fire.build_executable` generates it for `test_selfhost.py` (`fire.py`,
`do_imports=True`), without running gcc or linking.

    python3 tools/memcap.py --limit-gb 24 -- python3 tools/selfhost_ci.py selfhost.ci
    gcc-mp-15 -O0 -g0 -fgimple -I runtime $(python3-config --cflags) \
        -c -o /dev/null -x c selfhost.ci 2> gcc.log
    grep -E "^[^ ]+:[0-9]+:[0-9]+: error:" gcc.log | sed -E 's/.*error: //' | sort | uniq -c

Run it from a clean copy of the tree (`git archive HEAD | tar -x -C <dir>`), not a
checkout with untracked files. Count only `file:line:col: error:` lines, because gcc's
source echoes of string literals contain the word "error" too.
"""
import os
import sys


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else 'selfhost.ci'
    sys.path.insert(0, os.getcwd())
    import gimple_codegen
    src = open('fire.py').read()
    if gimple_codegen.module_may_have_supported_generator(src, filename='fire.py'):
        c_code, _cpp = gimple_codegen.compile_to_gimple_with_cpp(
            src, do_imports=True, filename='fire.py', link_objects_out=[])
    else:
        c_code = gimple_codegen.compile_to_gimple_cached(
            src, do_imports=True, filename='fire.py')
    with open(out, 'w') as f:
        f.write(c_code)
    return 0


if __name__ == '__main__':
    sys.exit(main())
