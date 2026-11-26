"""Regression pin: the presence-bit helpers take an ANNOTATED StructDef.

`mojo/middle/types.py`'s `presence_word_count(sdef)` read `sdef.presence_fields`
with an unannotated `sdef`; the self-hosted compile lowered that to a dynamic
attribute lookup on a boxed word and the compiler died on its first compile with
`AttributeError: presence_fields` (frame: `_gmp_emit_struct_definitions`). The
closure's C signature must be `(StructDef * sdef)`.
"""
import sys

import fire_compiler as N
from mojo.middle import types as T


def main() -> int:
    bad = []
    for fn in (T.presence_bit, T.presence_word_count, T.presence_set_stmt):
        ann = fn.__annotations__.get('sdef')
        if ann is not N.StructDef:
            bad.append('%s: sdef annotated %r' % (fn.__name__, ann))
    if bad:
        print('FAIL: ' + '; '.join(bad))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
