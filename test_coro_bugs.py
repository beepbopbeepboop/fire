#!/usr/bin/env python3
"""test_coro_bugs.py -- per-bug diagnostic for the A3 stack-switch
coroutine work. For every generator/coroutine bug report in bugs/ and
bugs/hard/, run compile_to_gimple_with_cpp(do_imports=True) on its Source
file with MOJO_CORO=stackswitch and report:

  LOWERED   compiled clean; N generator sites went through gimple_gen_coro
  COMPILE   compiled clean but no __mgco_ (no eligible generator, or the
            generator still went to the cpp path)
  RAISE     compilation raised -- the message is the current blocker

This is the "what's fixed / what remains" view. It stops at codegen (no
link / no stdlib dylib) so it runs in ~seconds/module, not ~minutes.

    MOJO_CORO=stackswitch python3 test_coro_bugs.py
    MOJO_CORO=stackswitch python3 test_coro_bugs.py <substr>   # filter
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_RE = re.compile(r'^Source file:\s*(\S+)', re.M)


def _bugs():
    out = []
    for d in ('bugs', 'bugs/hard'):
        dd = os.path.join(HERE, d)
        for fn in sorted(os.listdir(dd)):
            if not fn.endswith('.md'):
                continue
            low = fn.lower()
            if 'generator' not in low and 'coroutine' not in low and 'yield' not in low:
                continue
            p = os.path.join(dd, fn)
            m = SRC_RE.search(open(p, encoding='utf-8', errors='replace').read())
            if m and os.path.exists(m.group(1)):
                out.append((os.path.relpath(p, HERE), m.group(1)))
    return out


DO_IMPORTS = os.environ.get('CORO_BUGS_IMPORTS') == '1'


def main():
    filt = sys.argv[1] if len(sys.argv) > 1 else ''
    import gimple_codegen
    rows = []
    for report, src in _bugs():
        if filt and filt not in report:
            continue
        name = report.split('/')[-1].replace('CODEGEN_generator_function_Lib_', '').replace('.md', '')
        try:
            c, _ = gimple_codegen.compile_to_gimple_with_cpp(
                open(src).read(), do_imports=DO_IMPORTS, filename=src)
            lowered = c.count('__mgco_')
            # actually syntax-check the generated C -- a raise-free compile
            # can still emit broken C (bad yield lowering, etc.)
            import subprocess
            import tempfile
            rt = os.path.join(HERE, 'runtime')
            with tempfile.NamedTemporaryFile('w', suffix='.c', delete=False) as f:
                f.write(c)
                cf = f.name
            from build_config import find_gcc
            cc = subprocess.run([find_gcc(), '-fgimple', '-fsyntax-only', f'-I{rt}',
                                 '-w', cf], capture_output=True, text=True)
            os.unlink(cf)
            if cc.returncode != 0:
                first = next((l for l in cc.stderr.splitlines() if ' error:' in l), cc.stderr[:200])
                st, detail = 'CFAIL', f'({lowered} __mgco_) {first.strip()[:200]}'
            elif lowered:
                st, detail = 'LOWERED', f'{lowered} __mgco_ refs, C syntax-checks'
            else:
                st, detail = 'COMPILE', 'C ok, no eligible generator (cpp path / none)'
        except Exception as e:
            msg = re.sub(r'\s+', ' ', f'{type(e).__name__}: {e}').strip()
            st, detail = 'RAISE', msg[:240]
        rows.append((st, name, detail))
        print(f'{st:8s} {name:40s} {detail}', flush=True)

    counts = {}
    for st, *_ in rows:
        counts[st] = counts.get(st, 0) + 1
    print('\n' + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())))


if __name__ == '__main__':
    main()
