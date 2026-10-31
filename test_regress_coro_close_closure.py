"""Regression test for CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure.

The `_imported_global_accessors` early-return arm of `_lower_IdentExpr`
(emit_exprs.py) reads a module global through another module's accessor.
Two things must hold there, and the first one was missing:

1. The generator api recorded for the global by its store (in another
   module) must ride onto the read-back temp, else `.close()` / `next()`
   refuse with "no known generator API".
2. The read-back temp must be typed `MojoGenerator *`. The accessor's
   declared type comes from the export scan (module_loader.py types a
   `var NAME = call()` line as `void *`), not from the handle's real type,
   so a `void *` temp made `next()` refuse with "receiver typed void *".

The unit cases drive the arm directly on a GimpleGen with an accessor typed
the way the export scan types it. A cross-module compile that reaches this
arm with the api known is NOT yet reproducible: an imported generator global's
store is not recorded in the importer's gen (see the bug doc's Status).
"""
import gimple_codegen
from fire_compiler import IdentExpr


def _lower_read(api, poisoned, acc_ctype='void *'):
    gen = gimple_codegen.GimpleGen(do_imports=False, module_name='other')
    gen._imported_global_accessors['_coro'] = (acc_ctype,
                                               'sib__mojo_global_get__coro')
    gen._global_generator_api['_coro'] = api
    if poisoned:
        gen._global_generator_api_poisoned.add('_coro')
    ctype, temp = gen._lower_IdentExpr(IdentExpr('_coro'))
    return ctype, temp, gen._generator_var_api.get(temp)


def test_accessor_read_carries_generator_api():
    api = ('sentinel-generator-api',)
    ctype, temp, carried = _lower_read(api, poisoned=False)
    assert carried == api, f"accessor read {temp} lost the api: {carried!r}"


def test_accessor_read_of_generator_is_typed_as_generator():
    ctype, temp, carried = _lower_read(('sentinel-generator-api',),
                                       poisoned=False)
    assert ctype == 'MojoGenerator *', f"accessor read {temp} typed {ctype}"


def test_poisoned_name_does_not_carry_generator_api():
    ctype, temp, carried = _lower_read(('sentinel-generator-api',), poisoned=True)
    assert carried is None, f"poisoned name {temp} carried an api: {carried!r}"
    assert ctype == 'void *', f"poisoned name {temp} retyped as {ctype}"


if __name__ == '__main__':
    test_accessor_read_carries_generator_api()
    test_accessor_read_of_generator_is_typed_as_generator()
    test_poisoned_name_does_not_carry_generator_api()
    print("PASS: accessor-read generator api carry")
