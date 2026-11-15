#!/usr/bin/env python3
"""Regression: modular's test/mojo-parser/diagnostic_format.mojo. Its three RUN
lines (JSON stream, default text, and `--diagnostic-format json` combined with
`--use-mlir-diagnostics=true` being an error) are each reproduced here on an
equivalent file; when the modular checkout and FileCheck are present the real
test file is also run under FileCheck with the same check prefixes."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')
REAL = '/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-parser/diagnostic_format.mojo'
FILECHECK = '/opt/homebrew/opt/llvm/bin/FileCheck'

SRC = '''def main():
    _ = unknown_identifier
'''


def fire(args, path):
    p = subprocess.run([sys.executable, FIRE] + args + ['run', path],
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def with_file():
    d = tempfile.mkdtemp()
    f = os.path.join(d, 'd.mojo')
    open(f, 'w').write(SRC)
    return d, f


def test_json_stream_has_the_expected_fields():
    d, f = with_file()
    try:
        rc, out = fire(['--diagnostic-format', 'json', '--use-mlir-diagnostics=false'], f)
        assert rc == 1, rc
        recs = [json.loads(l) for l in out.splitlines()]
        first = recs[0]
        assert first['kind'] == 'error'
        assert first['message'] == "use of unknown declaration 'unknown_identifier'"
        diag = first['diagnostic']
        for k in ('file', 'fixIts', 'location', 'text'):
            assert k in diag, k
        assert set(diag['location']) == {'column', 'line'}
        assert recs[-1]['message'] == 'failed to parse the provided Mojo source module'
    finally:
        shutil.rmtree(d)


def test_default_text_format_is_an_error_line():
    d, f = with_file()
    try:
        rc, out = fire([], f)
        assert rc == 1 and ': error: use of unknown declaration' in out, out
    finally:
        shutil.rmtree(d)


def test_json_with_mlir_diagnostics_is_an_error():
    d, f = with_file()
    try:
        rc, out = fire(['--diagnostic-format', 'json', '--use-mlir-diagnostics=true'], f)
        assert rc == 1, rc
        assert out.strip() == ('{"kind":"error","message":"--diagnostic-format=json is '
                               'incompatible with --use-mlir-diagnostics=true"}'), out
    finally:
        shutil.rmtree(d)


def test_real_modular_test_under_filecheck():
    if not (os.path.exists(REAL) and os.path.exists(FILECHECK)):
        print('skip: modular checkout or FileCheck not present')
        return
    runs = [(['--diagnostic-format', 'json', '--use-mlir-diagnostics=false'], 'JSON'),
            ([], 'TEXT'),
            (['--diagnostic-format', 'json', '--use-mlir-diagnostics=true'], 'ERROR')]
    for args, prefix in runs:
        rc, out = fire(args, REAL)
        assert rc != 0, (prefix, rc)
        fc = subprocess.run([FILECHECK, REAL, '--check-prefix=' + prefix],
                            input=out, capture_output=True, text=True)
        assert fc.returncode == 0, (prefix, fc.stderr, out)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
