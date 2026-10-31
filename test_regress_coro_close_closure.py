"""Regression test for CODEGEN_the_collections_abc_coro_close_idiom_refuses_only_in_a_full_closure.

The `_imported_global_accessors` early-return arm of `_lower_IdentExpr`
(emit_exprs.py) reads a module global through another module's accessor and
returned a fresh read-back temp WITHOUT the generator api that the global's
store recorded. The read-back temp is then typed `MojoGenerator *`, so the
`.close()` / `next()` lowering refused with "no known generator API".

This drives the arm directly on a GimpleGen whose state says: `_coro` is an
imported global_var reached through an accessor, and a generator api was
recorded for it by a store in another module. The same state with the name
poisoned must NOT carry the api (the trust model is the owner's).
"""
import gimple_codegen
from fire_compiler import IdentExpr


def _lower_read(api, poisoned):
    gen = gimple_codegen.GimpleGen(do_imports=False, module_name='other')
    gen._imported_global_accessors['_coro'] = ('MojoGenerator *',
                                               'sib__mojo_global_get__coro')
    gen._global_generator_api['_coro'] = api
    if poisoned:
        gen._global_generator_api_poisoned.add('_coro')
    ctype, temp = gen._lower_IdentExpr(IdentExpr('_coro'))
    return ctype, temp, gen._generator_var_api.get(temp)


def test_accessor_read_carries_generator_api():
    api = ('sentinel-generator-api',)
    ctype, temp, carried = _lower_read(api, poisoned=False)
    assert ctype == 'MojoGenerator *', ctype
    assert carried == api, f"accessor read {temp} lost the api: {carried!r}"


def test_poisoned_name_does_not_carry_generator_api():
    ctype, temp, carried = _lower_read(('sentinel-generator-api',), poisoned=True)
    assert carried is None, f"poisoned name {temp} carried an api: {carried!r}"


if __name__ == '__main__':
    test_accessor_read_carries_generator_api()
    test_poisoned_name_does_not_carry_generator_api()
    print("PASS: accessor-read generator api carry")
