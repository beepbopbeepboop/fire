#!/usr/bin/env python3
"""Rewrite C-type string tests into TypeLattice predicates (doc/GIR.md stage 4).

    python3 tools/type_string_codemod.py            # rewrite every module in place
    python3 tools/type_string_codemod.py --check    # list what would change, change nothing

Turns `x == 'char *'` into `gimple_ctypes.TypeLattice.is_cstr(x)` (and `!=` into
`not ...`), likewise `'MojoList *'` -> is_list, `'_Bool'` -> is_bool,
`'double'` -> is_double, `'int64_t'` -> is_word, and `x.endswith(' *')` ->
ends_in_star(x). Only a simple left side (a name, attribute chain, subscripts,
or `_as_str(...)`) outside comments is rewritten; anything else is left for a
person. The generated C must stay byte-identical: run it on a few programs
before and after (tools/pydiff.py shows the output still matches CPython).

`test_type_string_ratchet.py` fails when a new string test is added; this tool
is the fix it points at.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LHS = (r"(?P<lhs>_as_str\([^()]*\)|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
       r"(?:\[[^\[\]]*\])*)")
EQ = {"char *": "is_cstr", "MojoList *": "is_list", "_Bool": "is_bool",
      "double": "is_double", "int64_t": "is_word"}
EQ_PATS = [(re.compile(r"(?P<pre>(?:^|[\s(])(?:not\s+)?)" + LHS
                       + r" (?P<op>[=!]=) '" + re.escape(lit)
                       + r"'(?P<post>(?![\w\[(.]))"), fn)
           for lit, fn in EQ.items()]
ENDS = re.compile(r"(?<![\w.])" + LHS + r"\.endswith\(' \*'\)")


def rewrite_line(line: str) -> str:
    if line.lstrip().startswith('#'):
        return line

    def ends(m):
        return 'gimple_ctypes.TypeLattice.ends_in_star(%s)' % m.group('lhs')
    line = ENDS.sub(ends, line)
    for pat, fn in EQ_PATS:
        def eq(m, fn=fn):
            call = 'gimple_ctypes.TypeLattice.%s(%s)' % (fn, m.group('lhs'))
            if m.group('op') == '!=':
                if m.group('pre').rstrip().endswith('not'):
                    return m.group(0)
                call = 'not ' + call
            return m.group('pre') + call + m.group('post')
        line = pat.sub(eq, line)
    return line


def modules() -> list:
    out = [os.path.join(HERE, 'gimple_codegen.py')]
    out += glob.glob(os.path.join(HERE, 'mojo', 'backend_gimple', '*.py'))
    out += glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))
    return sorted(p for p in out if not p.endswith(os.sep + 'types.py'))


def main(argv: list) -> int:
    check = '--check' in argv
    changed = 0
    for path in modules():
        src = open(path).read()
        if 'gimple_ctypes' not in src:
            continue
        new = '\n'.join(rewrite_line(l) for l in src.split('\n'))
        if new != src:
            changed += 1
            print(('would change ' if check else 'rewrote ') + os.path.relpath(path, HERE))
            if not check:
                open(path, 'w').write(new)
    return 1 if (check and changed) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
