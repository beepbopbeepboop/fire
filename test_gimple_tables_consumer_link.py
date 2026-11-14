#!/usr/bin/env python3
"""Quick repro/test for importing c_common.tables from a consumer program.

Part of bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part1.md.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CA_SRC = Path('/Users/mrs/net/Python-3.14.6/Tools/c-analyzer')


def main() -> int:
    if not CA_SRC.is_dir():
        print(f'SKIP: missing source tree {CA_SRC}')
        return 0
    with tempfile.TemporaryDirectory(dir=ROOT / '.tmp' if (ROOT / '.tmp').exists() else None) as td:
        ca = Path(td) / 'ca'
        shutil.copytree(CA_SRC, ca)
        (ca / 'data.tsv').write_text('a\tb\n1\t2\n3\t4\n')
        (ca / '_check_rt.py').write_text(
            "from c_common.tables import read_table\n\n"
            "def main():\n"
            "    for row in read_table('data.tsv', 'a\\tb'):\n"
            "        print(row)\n"
            "main()\n"
        )
        env = os.environ.copy()
        r = subprocess.run(
            [sys.executable, str(ROOT / 'fire.py'), 'build', '-o', '_check_rt', '_check_rt.py'],
            cwd=ca, env=env, capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            print('FAIL: build/link failed')
            return 1
        r = subprocess.run([str(ca / '_check_rt')], cwd=ca, capture_output=True, text=True)
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            print('FAIL: run failed')
            return 1
        out = r.stdout.strip().splitlines()
        if out != ["('1', '2')", "('3', '4')"]:
            print(f'FAIL: unexpected output: {out!r}')
            return 1
    print('PASS  test_gimple_tables_consumer_link')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
