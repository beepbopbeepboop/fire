"""Regression pin: every struct type a `_SELFHOST_SIGS` row names is declared
in the C of a compiler-source module that does not define it.

`_gmp_forward_selfhost_syms` forward-declares all of `_SELFHOST_SIGS` in the
preamble of every compiler-source module. A row naming `WordFacts *` with no
struct layout for `WordFacts` made `mojoc` (link mode, one TU per module) and
the stdlib dylib build of `mojo/middle/__init__.py` fail with
`unknown type name 'WordFacts'`; the whole-closure dump hid it because it
compiles `valueinfo.py` into the same TU.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimple_codegen  # noqa: E402

BUILTIN = {'MojoList', 'MojoDict', 'MojoSet', 'MojoStr', 'MojoBytes'}


def main() -> int:
    named = set()
    for _name, (ret, params, _mod) in gimple_codegen._SELFHOST_SIGS.items():
        for t in [ret] + list(params):
            m = re.fullmatch(r'([A-Za-z_]\w*) \*', t.strip())
            if m and m.group(1) not in BUILTIN and m.group(1) not in ('char', 'void'):
                named.add(m.group(1))
    path = os.path.join(HERE, 'version.py')
    with open(path) as f:
        src = f.read()
    c = gimple_codegen.compile_to_gimple(src, False, path)
    bad = []
    for n in sorted(named):
        if not re.search(r'typedef struct %s\b|\} %s;' % (n, n), c):
            bad.append(n)
    if bad:
        print('FAIL: _SELFHOST_SIGS names struct types with no declaration in '
              'version.py\'s C: %s' % ', '.join(bad))
        return 1
    print('PASS (%d struct types declared)' % len(named))
    return 0


if __name__ == '__main__':
    sys.exit(main())
