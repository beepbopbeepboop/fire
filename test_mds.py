"""Tests for the .md → LanguageSpec → mojo_compiler.py pipeline."""
import os
import py_compile
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def test_smoke_run():
    """run.py succeeds and produces a valid-Python mojo_compiler.py."""
    result = subprocess.run(
        [sys.executable, 'run.py'],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"run.py failed:\n{result.stderr}"
    out_path = os.path.join(HERE, 'mojo_compiler.py')
    assert os.path.exists(out_path), "mojo_compiler.py not produced"
    py_compile.compile(out_path, doraise=True)


def test_layout_spec():
    """Layout rules are extracted from the .md files, not hardcoded."""
    from fe_reader import FormalEnglishReader

    r = FormalEnglishReader()
    r.read(os.path.join(HERE, 'mojo-simple-statements.md'))
    r.read(os.path.join(HERE, 'mojo-manual-language-basics.md'))
    s = r.spec

    assert s.layout, 'layout is empty — not extracted from .md files'
    ld = s.layout[0]
    assert ld.has_indentation,          'has_indentation should be True'
    assert ld.indent_size == 4,         f'indent_size should be 4, got {ld.indent_size}'
    assert ld.continuation_char == '',  f'continuation_char should be empty (no backslash continuation in Mojo), got {ld.continuation_char!r}'
    assert ld.stmt_separator == ';',    f'stmt_separator should be ";", got {ld.stmt_separator!r}'
    assert ld.comment_char == '#',      f'comment_char should be "#", got {ld.comment_char!r}'


def test_spec_coverage():
    """After reading all .md files, the relevant spec fields are non-empty."""
    from fe_reader import FormalEnglishReader

    NEW_MDS = [
        'mojo-manual-language-basics.md',
        'mojo-manual-values.md',
        'mojo-manual-metaprogramming.md',
        'mojo-manual-pointers.md',
        'mojo-manual-python.md',
        'mojo-manual-gpu.md',
        'mojo-tools-and-faq.md',
    ]

    r = FormalEnglishReader()
    for f in NEW_MDS:
        r.read(os.path.join(HERE, f))
    s = r.spec

    assert s.arg_conventions, 'arg_conventions is empty'
    assert s.arg_conventions[0].conventions, 'no conventions found'
    assert 'read' in s.arg_conventions[0].conventions
    assert 'mut' in s.arg_conventions[0].conventions

    assert s.pointers, 'pointers is empty'
    assert 'UnsafePointer' in s.pointers[0].types
    assert 'ArcPointer' in s.pointers[0].types

    assert s.testing, 'testing is empty'
    assert s.testing[0].suite_type == 'TestSuite'
    assert 'assert_equal' in s.testing[0].assertion_fns
    assert 'assert_raises' in s.testing[0].assertion_fns

    assert s.python_interop, 'python_interop is empty'
    assert s.python_interop[0].import_fn == 'Python.import_module'
    assert s.python_interop[0].wrapper_type == 'PythonObject'

    assert s.structs, 'structs is empty'
    assert 'fieldwise_init' in s.structs[0].decorators

    assert s.traits, 'traits is empty'
    assert s.traits[0].has_where_clause
    assert len(s.traits[0].builtin_traits) >= 5

    assert s.lifecycle, 'lifecycle is empty'
    assert s.lifecycle[0].has_transfer_sigil
    assert s.lifecycle[0].has_copy_constructor
    assert s.lifecycle[0].has_move_constructor
    assert s.lifecycle[0].has_destructor

    assert s.parameters, 'parameters is empty'
    assert s.parameters[0].has_infer_only
    assert s.parameters[0].has_default

    assert s.gpu, 'gpu is empty'
    assert s.gpu[0].device_type == 'DeviceContext'
    assert 'DeviceBuffer' in s.gpu[0].buffer_types
    assert 'block_idx' in s.gpu[0].index_vars

    assert s.collection_types, 'collection_types is empty'
    found = s.collection_types[0].types
    assert 'List' in found
    assert 'Dict' in found
    assert 'Optional' in found


if __name__ == '__main__':
    tests = [test_smoke_run, test_layout_spec, test_spec_coverage]
    for t in tests:
        t()
        print(f'{t.__name__}: OK')
    print('All tests passed.')
