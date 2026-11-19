#!/usr/bin/env python3
"""Pin: the self-host closure may not bind `fields` by
`from dataclasses import fields` — the module-qualified spelling is modelled,
the bare alias is not.

Why this is a pin and not a style rule. `bootstrap-stage1-transitive` compiles
`fire.py`'s whole closure with the Python reference and counts every
`unavailable in compiled mode` weak stub in the dump. CPython's `dataclasses`
is not in the closure, so the codegen models the parts the compiler's own
source uses:

* `dataclasses.fields(x)` lowers to the reflection dispatch
  `_mojo_dispatch_fields(x)` (and a `for f in dataclasses.fields(x):` loop to
  its field-name walk);
* a `from dataclasses import fields as _dc_fields` alias is an unresolved
  import alias: its call site is a bare unknown name, so it gets the weak
  stub, and every such call in the compiled compiler returns 0.

The `_dc_fields` stubs in the closure's dump were exactly the second shape:
ten `dataclasses.fields(type(node))` calls in `cpp_core.py`'s AST copy/rewrite
walks. Under the self-hosted compiler every one returned 0, so those walks
saw an EMPTY field list and silently skipped the fields they copy; the
reference path was correct, so nothing else went red. They now read
`__dataclass_fields__` through `_cpp_field_names` (see its docstring), and
this pin keeps the from-import shape from coming back.

Scope: the syntactic import closure of `fire.py` (the set
`bootstrap-stage1-transitive` compiles), walked by the same
`cas.selfhost_closure_is_complete` the no-locals pin uses.

Run: python3 test_selfhost_no_dataclasses_fields_pin.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cas  # noqa: E402

# The files the removed `_dc_fields` calls lived in / the modelled module's
# users. Asserting they are IN the walk keeps this test honest if the closure
# walk changes and stops descending where the dump does.
WATCHED = (
    'mojo/backend_gimple/cpp_core.py',
    'mojo/middle/types.py',
    'mojo/backend_gimple/module_gen.py',
)


def unsupported_fields_calls_in(src: str, filename: str = '<input>') -> list:
    """`[(lineno, which)]` for every `dataclasses.fields` use the compiled
    path cannot lower.

    The module-qualified spelling is modelled: `dataclasses.fields(x)` lowers
    to the reflection dispatch `_mojo_dispatch_fields(x)` (and a
    `for f in dataclasses.fields(x):` loop to its field-name walk). The
    FROM-IMPORT spelling is not — `from dataclasses import fields [as X]`
    makes a bare call the codegen sees as an unknown name / unresolved import
    alias, which is the weak stub this pin exists for. Flag the binding.
    """
    tree = ast.parse(src, filename)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == 'dataclasses':
            for a in n.names:
                if a.name == 'fields':
                    hits.append((getattr(n, 'lineno', 0),
                                 'from dataclasses import fields'))
    return hits


def selfhost_closure() -> list:
    """The `.py` files `bootstrap-stage1-transitive` compiles, sorted."""
    missing, seen = cas.selfhost_closure_is_complete('fire.py')
    assert not missing, (
        'the fire.py closure reaches files the self-host key does not hash: '
        f'{sorted(missing)}')
    for name in WATCHED:
        assert name in seen, (
            f'{name} is not in the fire.py closure this test scans — the walk '
            'no longer descends where the dump does')
    return sorted(n for n in seen if n.endswith('.py'))


def test_no_unsupported_dataclasses_fields_in_selfhost_closure():
    failures = []
    scanned = 0
    for name in selfhost_closure():
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            src = f.read()
        scanned += 1
        for lineno, which in unsupported_fields_calls_in(src, name):
            failures.append(f'{name}:{lineno}: {which}')
    assert scanned > 50, f'only {scanned} modules scanned; the walk is broken'
    assert not failures, (
        'the self-host closure uses `dataclasses.fields` in a shape the '
        'compiled path cannot lower (it becomes an unavailable-in-compiled-'
        'mode weak stub returning 0). Use `__dataclass_fields__` (see '
        'cpp_core._cpp_field_names) or a `for f in dataclasses.fields(x):` '
        'loop:\n  ' + '\n  '.join(failures))


if __name__ == '__main__':
    test_no_unsupported_dataclasses_fields_in_selfhost_closure()
    print('PASS')
