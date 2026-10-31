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
import contextlib
import io
import os
import sys
import tempfile

import gimple_codegen
from fire_compiler import IdentExpr
from mojo.backend_gimple import emit_exprs
from mojo.backend_gimple import emit_infra as ginf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import probe_coro_close_refusal


def _lower_read(api, poisoned, acc_ctype='void *'):
    gen = gimple_codegen.GimpleGen(do_imports=False, module_name='other')
    gen._imported_global_accessors['_coro'] = (acc_ctype,
                                               'sib__mojo_global_get__coro')
    gen._imported_global_home['_coro'] = 'sib'
    key = ginf.global_generator_key('sib', '_coro')
    gen._global_generator_api[key] = api
    if poisoned:
        gen._global_generator_api_poisoned.add(key)
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


def test_probe_observes_read_without_changing_it():
    # tools/probe_coro_close_refusal.py wraps _lower_IdentExpr for the
    # refusal investigation. Its wrapper must return exactly what the real
    # arm returned (same ctype, same carried api) and report the read.
    api = ('sentinel-generator-api',)
    real = emit_exprs._lower_IdentExpr
    probe_coro_close_refusal._install('_coro')
    try:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ctype, temp, carried = _lower_read(api, poisoned=False)
    finally:
        emit_exprs._lower_IdentExpr = real
    assert (ctype, carried) == ('MojoGenerator *', api), (ctype, carried)
    line = err.getvalue()
    assert line.startswith('PROBE '), f"no probe line: {line!r}"
    assert f"temp={temp} " in line and "poisoned=False" in line, line


def test_same_bare_name_in_another_module_does_not_carry():
    # The generator-api tables are shared across the modules of one compile
    # and keyed by (defining module, name). A global `_coro` of module `sib`
    # must not lend its api to a read of an unrelated `_coro` owned by `mod_b`.
    gen = gimple_codegen.GimpleGen(do_imports=False, module_name='other')
    gen._imported_global_accessors['_coro'] = ('void *', 'mod_b__mojo_global_get__coro')
    gen._imported_global_home['_coro'] = 'mod_b'
    gen._global_generator_api[ginf.global_generator_key('sib', '_coro')] = ('sentinel-generator-api',)
    ctype, temp = gen._lower_IdentExpr(IdentExpr('_coro'))
    assert gen._generator_var_api.get(temp) is None, (
        f"mod_b's read {temp} inherited sib's generator api")
    assert ctype == 'void *', f"mod_b's read {temp} retyped as {ctype}"


def test_cross_module_generator_global_close_compiles():
    # `from sib import _coro` then `_coro.close()`: the store is recorded by
    # sib's own compile and read by the importer through sib's globals. The
    # importer must dispatch `.close()` to the generator, not stub it to 0
    # (`int64_t.close() — stubbed`), which is a silent wrong answer.
    sib_src = (
        "def _g():\n"
        "    yield 1\n"
        "    yield 2\n"
        "\n"
        "_coro = _g()\n"
    )
    entry_src = (
        "from sib import _coro\n"
        "\n"
        "_coro.close()\n"
        "print(\"ok\")\n"
    )
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'sib.py'), 'w') as f:
            f.write(sib_src)
        entry = os.path.join(d, 'entry.py')
        with open(entry, 'w') as f:
            f.write(entry_src)
        c_code, _cpp = gimple_codegen.compile_to_gimple_with_cpp(
            entry_src, do_imports=True, filename=entry)
    assert 'stubbed' not in c_code, "importer stubbed .close() on a generator global"
    assert '__mojo_gen_close (' in c_code, "importer emitted no generator close"


if __name__ == '__main__':
    test_accessor_read_carries_generator_api()
    test_accessor_read_of_generator_is_typed_as_generator()
    test_poisoned_name_does_not_carry_generator_api()
    test_probe_observes_read_without_changing_it()
    test_same_bare_name_in_another_module_does_not_carry()
    test_cross_module_generator_global_close_compiles()
    print("PASS: accessor-read generator api carry")
