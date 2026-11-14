#!/usr/bin/env python3
"""Reject self-imports inside ```mojo docstring code blocks.

Part 2 of DIAGNOSTICS_docstring_self_import: a docstring code block that
imports its own module must fail compilation with
`module 'X' cannot import itself`.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple


TMP = os.path.join(HERE, '.tmp')


def _write(name, src):
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    return path


def _compile_path(path):
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    return compile_to_gimple(src, do_imports=True, filename=path)


def test_docstring_self_import_fails():
    path = _write('docself_a.mojo', '''"""Example.

```mojo
import docself_a
```
"""

def main():
    pass
''')
    try:
        _compile_path(path)
    except SyntaxError as e:
        msg = str(e)
        assert "module 'docself_a' cannot import itself" in msg, msg
        return
    raise AssertionError('docstring self-import compiled without error')


def test_docstring_self_from_import_fails():
    path = _write('docself_b.mojo', '''"""Example.

```mojo
from docself_b import thing
```
"""

def main():
    pass
''')
    try:
        _compile_path(path)
    except SyntaxError as e:
        msg = str(e)
        assert "module 'docself_b' cannot import itself" in msg, msg
        return
    raise AssertionError('docstring self-from-import compiled without error')


def test_docstring_import_other_module_ok():
    path = _write('docself_c.mojo', '''"""Example.

```mojo
import os
```
"""

def main():
    pass
''')
    _compile_path(path)


def test_non_mojo_docstring_block_not_checked():
    path = _write('docself_d.mojo', '''"""Example.

```python
import docself_d
```
"""

def main():
    pass
''')
    _compile_path(path)


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
