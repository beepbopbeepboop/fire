#!/usr/bin/env python3
"""A pattern built AT RUN TIME (`re.compile(<expr>)`, a module-level compiled
pattern, `re.search(pat, s)`) compiled by fire.py and RUN, its output required to
equal CPython's on the same text.

Two layers:
  * the engine alone (runtime/fire_re_engine.inc) against `re` on a table of
    patterns -- spans of every group, by byte offset;
  * a compiled program exercising the object model: compile / match / search /
    fullmatch / findall / sub / split / finditer, match.group/start/end/span/groups,
    a pattern's `.match` read as a value, module-level patterns, flags.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

ENGINE_CASES = [
    (1, 0, r'a+b', 'xaab'), (0, 0, r'a+b', 'aab'), (2, 0, r'a+b', 'aab'), (2, 0, r'a+b', 'aabx'),
    (1, 0, r'([*?[])', 'a*b'), (1, 0, r'(a)(b)?', 'ac'), (1, 0, r'(?:ab)+', 'xababab'),
    (1, 0, r'a|b|cd', 'xcd'), (1, 0, r'[a-c]+', 'xxabcabxx'), (1, 0, r'[^a-c]+', 'abxyzabc'),
    (1, 0, r'\d+\.\d*', 'pi 3.14159 e'), (1, 0, r'\bfoo\b', 'a foo b'), (1, 0, r'\bfoo\b', 'afoob'),
    (1, 0, r'a.c', 'a\nc'), (1, 16, r'a.c', 'a\nc'), (1, 2, r'ABC', 'xabcx'),
    (1, 0, r'^b', 'a\nb'), (1, 8, r'^b', 'a\nb'), (1, 0, r'a$', 'a\n'), (1, 0, r'a\Z', 'a\n'),
    (1, 0, r'(?s:.)', '\n'), (1, 0, r'a*?b', 'aaab'), (1, 0, r'a{2,3}', 'aaaa'), (1, 0, r'a{2}', 'a'),
    (1, 0, r'x*', 'aaa'), (1, 0, r'(a|ab)(c|bcd)(d*)', 'abcd'), (1, 0, r'(?=a)a', 'a'),
    (1, 0, r'a(?!b)', 'abac'), (1, 0, r'(?<=a)b', 'ab'), (1, 0, r'(?<!a)b', 'abcb'),
    (1, 0, r'(?>a+)ab', 'aaab'), (1, 0, r'(a)\1', 'aa'), (1, 0, r'(?P<x>a)(?P=x)', 'aa'),
    (1, 0, r'[\d\s]+', 'ab 12 3c'), (1, 0, r'\w+', 'hé llo'), (2, 16, r'(?s:.*)\Z', 'a\nb'),
    (2, 0, r'[^/]*/[^/]*', 'ab/cd'), (2, 0, r'(?s:a.*)\Z', 'a/b/c'), (1, 0, r'a++b', 'aaab'),
    (1, 0, r'é+', 'xééx'), (1, 0, r'[é-ü]+', 'aéüb'),
    (1, 0, r'a\.b', 'a.b'), (1, 0, r'[.]', 'a.b'), (1, 0, r'(?i)abc', 'xABC'),
    (1, 0, r'a{,2}', 'aaa'), (1, 0, r'a{x', 'a{x'), (2, 0, r'(?s:.*\.py)\z', 'abc.py'),
    (2, 0, r'(?s:a(?>.*?b)c.*)\z', 'axxbcyy'),
]


def engine_layer():
    src = os.path.join(HERE, 'runtime', 'test_fire_re_engine.c')
    exe = os.path.join(tempfile.mkdtemp(prefix='re_engine_'), 'tre')
    r = subprocess.run(['gcc', '-O1', '-o', exe, src], capture_output=True, text=True)
    if r.returncode:
        print('FAIL engine build:', r.stderr[:500])
        return 1
    bad = 0
    for mode, fl, pat, text in ENGINE_CASES:
        f = {0: re.match, 1: re.search, 2: re.fullmatch}[mode]
        m = f(pat, text, flags=fl)
        if m is None:
            want = 'None'
        else:
            tb = lambda i: len(text[:i].encode()) if i >= 0 else -1
            want = ' '.join(f'{tb(m.span(i)[0])},{tb(m.span(i)[1])}' for i in range(m.re.groups + 1))
        got = subprocess.run([exe, str(mode), str(fl), pat, text], capture_output=True, text=True).stdout.strip()
        if got != want:
            bad += 1
            print('FAIL engine', mode, fl, repr(pat), repr(text), 'want', want, 'got', got)
    print(f'{"PASS" if not bad else "FAIL"}  re engine vs CPython: {len(ENGINE_CASES) - bad}/{len(ENGINE_CASES)}')
    return bad


PROGRAM = r'''
import re

magic = re.compile('([*?[])')

def make_sep():
    parts = [',', '\\s', '*']
    return ''.join(parts)

def has_magic(s):
    return magic.search(s) is not None

def main():
    print(has_magic("a*"), has_magic("ab"))
    p = re.compile('(a+)(b)')
    m = p.match("aab")
    print(m is not None, m.group(0), m.group(1), m.start(1), m.end(2), m.span(2), m.groups())
    print(re.search('x(y*)z', "..xyyz.").group(1))
    print(re.fullmatch('a.c', "abc") is not None, re.fullmatch('a.c', "abcd") is not None)
    pat = "[" + "a-c" + "]+"
    print(re.match(pat, "abcabd").group())
    f = re.compile('b+').match
    print(f("bbbc").group(), f("xbb") is None)
    print(re.findall('a(.)', "abacad"), re.findall('a.', "abacad"))
    print(re.compile('A', re.IGNORECASE).match("a") is not None)
    q = re.compile(make_sep())
    print(q.split("a, b,c"))
    print(magic.sub(r'[\1]', "a*b?c"))
    print([x.group() for x in re.compile(r'\d+').finditer("a1b22c333")])
    named = re.compile(r'(?P<k>\w+)=(?P<v>\w+)').match("key=val")
    print(named.group('k'), named.group('v'))
    print(re.compile(r'(?s:a.*)\z').match("a\nb") is not None)

main()
'''


def program_layer():
    d = tempfile.mkdtemp(prefix='re_prog_')
    src = os.path.join(d, 'prog.py')
    with open(src, 'w') as fh:
        fh.write(PROGRAM)
    want = subprocess.run([sys.executable, src], capture_output=True, text=True).stdout
    exe = os.path.join(d, 'prog')
    b = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', src, '-o', exe],
                       capture_output=True, text=True)
    if not os.path.exists(exe):
        print('FAIL program build:', (b.stdout + b.stderr)[-800:])
        return 1
    got = subprocess.run([exe], capture_output=True).stdout.decode('utf-8', 'replace')
    if got != want:
        print('FAIL compiled re program differs from CPython\n--- CPython\n' + want + '--- compiled\n' + got)
        return 1
    print('PASS  compiled run-time re program matches CPython')
    return 0


if __name__ == '__main__':
    bad = engine_layer()
    if '--engine-only' not in sys.argv:
        bad += program_layer()
    sys.exit(1 if bad else 0)
