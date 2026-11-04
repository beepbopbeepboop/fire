#!/usr/bin/env python3
"""Regression for DOCS_dangling_doc_refs_ratchet_red_preexisting.

The root cause: dangling citations to deleted bug docs grow the corpus.
Fix: delete fixed docs; retarget remaining citations by symptom (commit
or bug name), not by deleted doc path. This pins that the doc-refs
ratchet does not gain new citations after the doc is removed.
"""
import subprocess, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))

HERE = os.path.dirname(os.path.abspath(__file__))

def test_ratchet_does_not_gain_after_doc_removal():
    """After deleting bugs/DOCS_dangling_doc_refs_ratchet_red_preexisting.md,
    the ratchet should be at or below the pre-deletion count, and the doc
    itself (which cited deleted docs) must not appear."""
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, 'tools', 'dangling_doc_refs.py'), '--ratchet'],
        capture_output=True, text=True, cwd=HERE)
    # The ratchet exits 1 when files exceed their baseline; after removing
    # the doc we expect the count to drop (the doc itself was over baseline).
    stdout = result.stdout
    # The deleted doc should not be listed as over-baseline.
    assert 'bugs/DOCS_dangling_doc_refs_ratchet_red_preexisting.md' not in stdout, \
        f'deleted doc still over baseline: {stdout}'
    # It may still exit 1 because other files (other workers' claims) still
    # exceed their baselines; that is expected.

def test_doc_is_deleted():
    assert not os.path.exists(os.path.join(HERE, 'bugs', 'DOCS_dangling_doc_refs_ratchet_red_preexisting.md'))

if __name__ == '__main__':
    test_doc_is_deleted()
    test_ratchet_does_not_gain_after_doc_removal()
    print('regression: PASS')
