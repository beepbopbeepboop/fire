"""Regression pin: a field is not minted presence-tracked after a store of it was
emitted without a bit.

An import cycle compiles a module that STORES `gen.var_types = ...` before the
module that defines `GimpleGen` finds the phantom field. Minting it then guarded
every later READ on a presence bit that store never sets, and the self-hosted
compiler raised `AttributeError: 'GimpleGen' object has no attribute 'var_types'`
on its first compile with a call. `presence_set_emit` records the store;
`_mark_presence_field` refuses to mint a recorded field.
"""
import sys

import fire_compiler as N
import mojo.backend_gimple.module_gen as MG
import mojo.middle.types as T


class _Gen:
    def __init__(self):
        self._stores_without_presence = set()
        self.emitted = []

    def _new_temp(self, t):
        return '_t'

    def _binop_into(self, *a):
        self.emitted.append(a)


def main() -> int:
    sdef = N.StructDef('C', [], [])
    sdef.presence_fields = []
    gen = _Gen()
    # a store compiled before the field is minted: no bit, and it is recorded
    T.presence_set_emit(gen, sdef, 'x', 'obj', '->')
    if 'C\x1fx' not in gen._stores_without_presence:
        print('FAIL: a store emitted without a bit was not recorded')
        return 1
    MG._mark_presence_field(sdef, 'x', gen._stores_without_presence)
    if 'x' in sdef.presence_fields:
        print('FAIL: a field with an earlier bit-less store was minted presence-tracked')
        return 1
    # a field with no earlier store is still minted
    MG._mark_presence_field(sdef, 'y', gen._stores_without_presence)
    if sdef.presence_fields != ['y']:
        print('FAIL: an ordinary phantom field is no longer minted: %r' % sdef.presence_fields)
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
