#!/usr/bin/env python3
"""Ratchet over tools/pydiff_corpus: every program listed in
tools/pydiff_ok.txt must keep printing exactly what CPython prints.

    python3 test_pydiff_ratchet.py            # check the listed programs
    python3 test_pydiff_ratchet.py --update   # also run the rest of the corpus
                                              # and ADD newly passing programs

The list may only grow. A program that stops matching CPython is a
regression, whoever's change it was; fix the change, or if the program itself
was wrong, remove its line in the same commit and say why.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import pydiff  # noqa: E402

CORPUS = os.path.join(HERE, 'tools', 'pydiff_corpus')
OK_LIST = os.path.join(HERE, 'tools', 'pydiff_ok.txt')

# Programs still under active repair that must at least STOP CRASHING. They
# are deliberately NOT in pydiff_ok.txt: their stdout still differs from
# CPython, so adding them there would make the ratchet red. This is the pin
# for the narrower promise "the compiled program reaches its end", which is
# the regression the mixed-return ABI fixes closed.
NO_CRASH = [
    'flow/04_ternary_mixed_types.py',
    'flow/33_mixed_type_variable.py',
    'params/10_none_or_value_arg.py',
]


def corpus_files() -> list:
    out = []
    for root, _dirs, names in os.walk(CORPUS):
        for n in sorted(names):
            if n.endswith('.py'):
                out.append(os.path.relpath(os.path.join(root, n), CORPUS))
    return sorted(out)


def listed() -> list:
    if not os.path.exists(OK_LIST):
        return []
    return [l.strip() for l in open(OK_LIST) if l.strip() and not l.startswith('#')]


def run_all(rels: list) -> dict:
    jobs = min(8, os.cpu_count() or 2)
    paths = [os.path.join(CORPUS, r) for r in rels]
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(pydiff.run_child, paths))
    return {r: res for r, res in zip(rels, results)}


def main(argv: list) -> int:
    update = '--update' in argv
    want = listed()
    missing = [r for r in want if not os.path.exists(os.path.join(CORPUS, r))]
    todo = corpus_files() if update else want
    results = run_all([r for r in todo if r not in missing])
    bad = [r for r in want if r in results and results[r]['verdict'] != 'OK']
    no_crash = [r for r in NO_CRASH if r not in results]
    if no_crash:
        results.update(run_all(no_crash))
    for r in NO_CRASH:
        if results.get(r, {}).get('verdict') == 'CRASH':
            print('  CRASH %s: compiled program still dies' % r)
            bad.append(r)
    for r in missing:
        print('  FAIL  %s: listed but not in the corpus' % r)
    for r in bad:
        print('  FAIL  %s: %s' % (r, results[r]['verdict']))
        print('        ' + pydiff.report(r, results[r]).replace('\n', '\n        '))
    fixed = []
    if update:
        fixed = [r for r in corpus_files() if r not in want
                 and results.get(r, {}).get('verdict') == 'OK']
        if fixed and not bad and not missing:
            with open(OK_LIST, 'w') as fh:
                fh.write('# Programs in tools/pydiff_corpus that match CPython. May only grow.\n')
                for r in sorted(set(want) | set(fixed)):
                    fh.write(r + '\n')
        print('  %d newly passing program(s) %s' % (
            len(fixed), 'added to tools/pydiff_ok.txt' if fixed and not bad else 'found'))
    print('%d listed programs checked, %d failure(s)' % (len(want), len(bad) + len(missing)))
    return 1 if (bad or missing) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
