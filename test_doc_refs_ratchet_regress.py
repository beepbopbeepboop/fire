#!/usr/bin/env python3
"""Regression for DOCS_dangling_doc_refs_ratchet_red_preexisting.

The root cause: dangling citations to deleted bug docs grow the corpus.
Fix: delete fixed docs; retarget remaining citations by symptom (commit
or bug name), not by deleted doc path. This pins that the doc-refs
ratchet does not gain new citations after the doc is removed.

Also pins the deletion of the closed 2026-11-11 make-check round doc
(SUITE_make_check_round_2026-11-11.md): every one of its six jobs was
fixed on master, and its one citation of a deleted doc (the
gate-formal-host-import-shapes.md that went away with its fix) put the
file over its 0 ratchet baseline. A closed round doc stays out of the
queue, so the round's close deletes it.
"""
import subprocess, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
import dangling_refs_baseline  # noqa: E402 — after the sys.path line

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


def test_gate_doc_refs_ratchet_red_on_master_fixed():
    """The GATE_doc_refs_ratchet_red_on_master bug doc was deleted after baseline regenerated."""
    assert not os.path.exists(os.path.join(HERE, 'bugs', 'mid', 'GATE_doc_refs_ratchet_red_on_master.md'))
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, 'tools', 'dangling_doc_refs.py'), '--ratchet'],
        capture_output=True, text=True, cwd=HERE)
    assert result.returncode == 0, result.stdout + result.stderr


def test_round_2026_11_11_doc_is_deleted():
    """The 2026-11-11 `make check` round report is closed: all six jobs were
    fixed on master, so the doc is deleted from the queue rather than left
    behind with a Status history (bugs/ is a queue of work, not an archive)."""
    assert not os.path.exists(
        os.path.join(HERE, 'bugs', 'SUITE_make_check_round_2026-11-11.md'))


def test_round_2026_11_11_doc_not_over_ratchet_baseline():
    """The round doc's one citation of a deleted doc (the
    gate-formal-host-import-shapes.md that went away with its fix,
    5f7360ac0) put it over its 0 ratchet baseline. With the doc deleted the
    ratchet must not flag it. It may still exit 1 for other files (other
    workers' claims); that is expected and out of this test's scope."""
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, 'tools', 'dangling_doc_refs.py'), '--ratchet'],
        capture_output=True, text=True, cwd=HERE)
    assert 'SUITE_make_check_round_2026-11-11.md' not in result.stdout, \
        f'closed round doc still over its ratchet baseline: {result.stdout}'


def test_two_preexisting_gains_are_pinned():
    """SUITE_doc_refs_ratchet_two_preexisting_gains (2026-11-13): the doc-refs
    ratchet was red on master for two pre-existing citation gains, neither
    caused by the lane that filed the bug —
      * the self-host closure GATE doc cited the deleted parse_module
        sig-table doc (CODEGEN_selfhost_sig_table_parse_module_recover, fixed
        in 32d9c79c7) by its `bugs/` path, and
      * bugs/hard/README.md kept the row of the deleted align-decorator doc
        (DIAGNOSTICS_align_decorator, whose three parts all landed) bare.
    The fix retargeted the GATE doc's citation at the bug and its fix commit,
    dropped the dead row, and deleted this bug's own doc, which cited the
    align-decorator doc in a sentence the bare walk could not skip. The GATE
    doc has since been fixed and deleted in its own commit (the self-host
    closure compiles and the gate job is green), so its half is pinned by
    absence: a restored copy would re-cite the sig-table doc again. This pins
    the ratchet green and keeps both files free of the deleted docs. The stems
    are assembled below without the suffix and never written through as one
    token: this file is a tracked .py, its ratchet budget is already used by
    the pins above, and a citation in it would be the regression this test
    exists to pin."""
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, 'tools', 'dangling_doc_refs.py'), '--ratchet'],
        capture_output=True, text=True, cwd=HERE)
    assert result.returncode == 0, \
        f'ratchet still red after the two preexisting gains were fixed:\n' \
        f'{result.stdout}{result.stderr}'
    gate_doc = 'GATE_selfhost_closure_cannot_compile' + '.md'
    assert not os.path.exists(os.path.join(HERE, 'bugs', gate_doc)), \
        'the fixed GATE doc is back; it cited the deleted sig-table doc'
    align_doc = 'DIAGNOSTICS_align_decorator' + '.md'
    with open(os.path.join(HERE, 'bugs', 'hard', 'README.md'), encoding='utf-8') as f:
        assert align_doc not in f.read(), \
            'deleted align-decorator row back in the hard README'
    bug_doc = 'SUITE_doc_refs_ratchet_two_preexisting_gains' + '.md'
    assert not os.path.exists(os.path.join(HERE, 'bugs', bug_doc)), \
        'the bug doc for this ratchet red should be deleted with the fix'


def test_gate_doc_refs_red_on_master_is_retired():
    """The 2026-11-20 `gate-doc-refs` filing: the ratchet was red on master
    for one gain, `tools/test_integrate_probe_loop.py` naming a doc-shaped
    FIXTURE inside a mock. The name does not exist by construction, so it is
    the deliberate-fixture case the tool documents, and the ledger is the
    sanctioned place to say so. The fix (3783b2cf1) added that entry and the
    doc leaves the queue with it. This pins both halves: the entry stays, and
    the ratchet stays green. The doc name is assembled from its stem so this
    file does not itself become the next citation of the deleted doc."""
    assert dangling_refs_baseline.BASELINE.get(
        'tools/test_integrate_probe_loop.py') == 1, \
        'the deliberate mock fixture lost its ledger entry; the ratchet goes red'
    assert not os.path.exists(
        os.path.join(HERE, 'bugs', 'gate-doc-refs' + '.md')), \
        'the gate-doc-refs doc is back in the queue after its fix'
    result = subprocess.run(
        [sys.executable, os.path.join(HERE, 'tools', 'dangling_doc_refs.py'), '--ratchet'],
        capture_output=True, text=True, cwd=HERE)
    assert result.returncode == 0, \
        f'ratchet red after the fixture entry landed:\n{result.stdout}{result.stderr}'


def test_doc_refs_job_is_enabled():
    """Deleting the doc is only HALF the retirement: the gate filing at
    `0d832b8d39` also switched the job off with a `disabled=` marker, and a job
    that is registered and never run cannot report the ratchet green. The
    marker and the doc are the two halves of one state, so they must move
    together — `disabled_problems()` refuses an import where only one of them
    is left behind, and this pins the registration itself against a re-added
    marker on a doc that is back.

    No `expect=` either: the red this filing recorded was one file over its
    ceiling and that file was deleted with its own fix, so the job is green and
    an `expect=` would be a marker that forgives a real regression."""
    sys.path.insert(0, os.path.join(HERE, 'tools'))
    import suite  # noqa: E402 — after the sys.path line
    spec = suite.REGISTRY['doc-refs']
    assert not spec.disabled, \
        f'doc-refs is switched off again (disabled={spec.disabled!r}); a ' \
        f'green ratchet is a job the gate has to run'
    assert not spec.expect, \
        f'doc-refs is marked known-failing again (expect={spec.expect!r})'


if __name__ == '__main__':
    test_doc_is_deleted()
    test_ratchet_does_not_gain_after_doc_removal()
    test_round_2026_11_11_doc_is_deleted()
    test_round_2026_11_11_doc_not_over_ratchet_baseline()
    test_gate_doc_refs_ratchet_red_on_master_fixed()
    test_two_preexisting_gains_are_pinned()
    test_gate_doc_refs_red_on_master_is_retired()
    test_doc_refs_job_is_enabled()
    print('regression: PASS')
