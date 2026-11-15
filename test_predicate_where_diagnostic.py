#!/usr/bin/env python3
"""Regression: a `where` clause that CALLS a predicate with provable integer
arguments. A predicate that is not `@always_inline("builtin")` cannot be folded:
`invalid call to 'f': lacking evidence to prove correctness` with the four
notes (cannot prove constraint, needs evidence for 'pred(Int(0))', cannot
evaluate call to non-builtin function, provide evidence); a builtin one is
evaluated from its body and reported as an ordinary violated constraint with the
predicate spelled `pred(x)`. Expected text captured from `tools/mojo build -I`
(DIAGNOSTICS_formatting_modular part 1, groups E/F)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

PACKAGE = '@always_inline("builtin")\ndef foldable_predicate(y: Int) -> Bool:\n    return y > 0\n\n\ndef unfoldable_predicate(y: Int) -> Bool:\n    return y > 0\n\n\ndef unprovable[x: Int]() where unfoldable_predicate(x):\n    pass\n'

MAIN = 'import pk\n\n\ndef my_unprovable[x: Int]() where pk.unfoldable_predicate(x):\n    pass\n\n\ndef my_foldable[x: Int]() where pk.foldable_predicate(x):\n    pass\n\n\ndef main():\n    _ = my_unprovable[0]()\n    _ = pk.unprovable[0]()\n    my_foldable[0]()\n    my_foldable[1]()\n'

WANT = "M:13:9: error: invalid call to 'my_unprovable': lacking evidence to prove correctness\n    _ = my_unprovable[0]()\n        ^~~~~~~~~~~~~\nM:4:5: note: cannot prove constraint for candidate\ndef my_unprovable[x: Int]() where pk.unfoldable_predicate(x):\n    ^\nM:4:35: note: constraint declared here needs evidence for 'unfoldable_predicate(Int(0))'\ndef my_unprovable[x: Int]() where pk.unfoldable_predicate(x):\n                                  ^\nImported from M:1:\nP:6:5: note: cannot evaluate call to non-builtin function declared here\ndef unfoldable_predicate(y: Int) -> Bool:\n    ^\nM:13:9: note: provide evidence for the constraint here to aid in candidate selection\n    _ = my_unprovable[0]()\n        ^\nM:14:11: error: invalid call to 'unprovable': lacking evidence to prove correctness\n    _ = pk.unprovable[0]()\n        ~~^~~~~~~~~~~\nImported from M:1:\nP:10:5: note: cannot prove constraint for candidate\ndef unprovable[x: Int]() where unfoldable_predicate(x):\n    ^\nImported from M:1:\nP:10:32: note: constraint declared here needs evidence for 'unfoldable_predicate(Int(0))'\ndef unprovable[x: Int]() where unfoldable_predicate(x):\n                               ^\nImported from M:1:\nP:6:5: note: cannot evaluate call to non-builtin function declared here\ndef unfoldable_predicate(y: Int) -> Bool:\n    ^\nM:14:11: note: provide evidence for the constraint here to aid in candidate selection\n    _ = pk.unprovable[0]()\n          ^\nM:15:5: error: invalid call to 'my_foldable': violated constraint\n    my_foldable[0]()\n    ^~~~~~~~~~~\nM:8:33: note: constraint declared here evaluated to False, expected 'foldable_predicate(x)'\ndef my_foldable[x: Int]() where pk.foldable_predicate(x):\n                                ^\nM:8:5: note: function declared here\ndef my_foldable[x: Int]() where pk.foldable_predicate(x):\n    ^\n"


def test_lacking_evidence_and_foldable_predicate():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'pk'))
        pk = os.path.join(d, 'pk', '__init__.mojo')
        open(pk, 'w').write(PACKAGE)
        m = os.path.join(d, 'e.mojo')
        open(m, 'w').write(MAIN)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(pk, 'P').replace(m, 'M')
        assert p.returncode == 1 and err == WANT, err


if __name__ == '__main__':
    test_lacking_evidence_and_foldable_predicate()
    print('ok test_lacking_evidence_and_foldable_predicate')
    print('all tests passed')
