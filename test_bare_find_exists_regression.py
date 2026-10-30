#!/usr/bin/env python3
"""Regression for bugs/DOCS_merge_left_citations_of_the_docs_the_branches_deleted.md
The root cause was bare_find's existence test being inverted for bug docs,
so live docs (e.g. FORMAL_known_limits.md) were reported as dangling.
This pins the fix: live bug docs must never appear in bare_find output."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
import dangling_doc_refs

def test_bare_find_does_not_report_live_bug_docs():
    have = dangling_doc_refs.existing_docs()
    bare_by_doc, bare_by_file = dangling_doc_refs.bare_find()
    live = {n.rsplit('/', 1)[-1]: v for n, v in bare_by_doc.items()
            if f'bugs/{n}' in have}
    assert not live, (
        f'bare_find still inverted: {sum(len(v) for v in live.values())} '
        f'bare citations of {len(live)} live docs: {sorted(live)[:5]}')

def test_bare_find_is_not_vacuous():
    bare_by_doc, _ = dangling_doc_refs.bare_find()
    assert sum(len(v) for v in bare_by_doc.values()) >= 196, \
        f'bare corpus too small ({sum(len(v) for v in bare_by_doc.values())}), fix may have over-skipped'

if __name__ == '__main__':
    test_bare_find_does_not_report_live_bug_docs()
    test_bare_find_is_not_vacuous()
    print('bare_find regression: PASS')
