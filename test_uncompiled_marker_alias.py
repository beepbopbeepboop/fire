"""Regression pin: a call through an ALIASED module import is not an
uncompiled-module raise when the aliased module was compiled.

`import mojo.middle.import_ambiguity as _import_ambiguity` then
`_import_ambiguity.check_module_from_imports(...)` was lowered to
`mojo_module_not_compiled`, because `_uncompiled_module_marker` asked
`_compiled_modules` about the ALIAS (`_import_ambiguity`) instead of the module
it names. The self-hosted compiler died on its first compile with
`NotImplementedError: ... module 'mojo.middle.import_ambiguity' is not compiled
into this binary`; the closure held 165 such call sites (monomorphize.mangle,
module_loader.module_name_for_path, comptime.eval_const, ...), 5 after the fix.
"""
import sys

import fire_compiler as N
import mojo.backend_gimple.emit_methods as em


class _Gen:
    def __init__(self, compiled):
        self._module_alias_names = {'_ia'}
        self.imported_symbols = {'_ia': {'module': 'zz_no_such_pkg.mod'}}
        self._compiled_modules = compiled

    def _submodule_source_path(self, module):
        return None


def _call():
    return N.CallExpr(N.MemberExpr(N.IdentExpr('_ia'), 'f'), [], [])


def main() -> int:
    got = em._uncompiled_module_marker(_Gen({'zz_no_such_pkg.mod'}), _call())
    if got != '':
        print('FAIL: an aliased import of a compiled module is reported uncompiled: %r' % got)
        return 1
    # ...and a module that was NOT compiled still is.
    got = em._uncompiled_module_marker(_Gen(set()), _call())
    if got != 'zz_no_such_pkg.mod':
        print('FAIL: an uncompiled aliased module is no longer reported: %r' % got)
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
