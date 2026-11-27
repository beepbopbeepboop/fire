#!/usr/bin/env python3
"""Regression: the self-host closure's ModuleLoader method symbols are qualified.

Symptom (fire1 link, 2026-11-27, `make -k -j20` in the GCC build dir):

    Undefined symbols for architecture arm64:
      "_ModuleLoader___init__", referenced from:
          __mojo_getattr_ModuleLoader in fire.o
      "_ModuleLoader_load_module", ...
      "_ModuleLoader__mojo_type_to_c", ...

`module_loader.py`'s own compile emits every method as
`module_loader_ModuleLoader_<name>`, but `build_stdlib_dylib.py` (which
`from module_loader import ... ModuleLoader`) emitted its declarations, call
sites, and `_mojo_getattr_ModuleLoader` arms under the BARE name. The two
halves never met, so link failed. The whole-closure compile has no
`_register_imported_structs` registration (it is dylib-only and returns early
when `do_imports`), so `GimpleGen.__init__` seeds the home explicitly, the same
way it already does for `Parser`, `Interpreter`, and `WordFacts`.

This pins both halves: the seed applies to a fresh gen (so every module in the
closure agrees on the spelling), and a genuine LOCAL class of the same name
still uses the compiling module's own qualifier (the tier-1 rule in
`_struct_method_qualifier` must continue to win over the seed).

Run:  python3 test_codegen_selfhost_moduleloader_method_symbols.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import gimple_codegen  # noqa: E402


METHOD_SYMBOLS = (
    ('__init__', 'module_loader_ModuleLoader___init__'),
    ('load_module', 'module_loader_ModuleLoader_load_module'),
    ('_mojo_type_to_c', 'module_loader_ModuleLoader__mojo_type_to_c'),
    ('can_resolve_module_path',
     'module_loader_ModuleLoader_can_resolve_module_path'),
)


def check():
    gen = gimple_codegen.GimpleGen()
    # The seed lives in gen_module's self-host layout pass, not in __init__.
    import mojo.backend_gimple.module_gen as mgen
    mgen._gmp_selfhost_ast_layouts(gen, True)
    qualifier = gen._struct_method_qualifier('ModuleLoader')
    assert qualifier == 'module_loader', (
        f'ModuleLoader qualifier: expected module_loader, got {qualifier!r}'
    )
    for method, expected in METHOD_SYMBOLS:
        got = gen._struct_method_csym('ModuleLoader', method, '')
        assert got == expected, (
            f'ModuleLoader.{method}: expected {expected!r}, got {got!r}'
        )

    # A module that DEFINES its own class with this same bare name keeps its
    # own prefix: the local tier outranks the closure seed.
    local = gimple_codegen.GimpleGen()
    local.module_name = 'usermod'
    setattr(local, '_local_struct_names', {'ModuleLoader'})
    got = local._struct_method_qualifier('ModuleLoader')
    assert got == 'usermod', (
        f'local ModuleLoader qualifier: expected usermod, got {got!r}'
    )
    return True


if __name__ == '__main__':
    check()
    print('OK: ModuleLoader method symbols are module_loader_-qualified; '
          'a local same-named class keeps its own home')
