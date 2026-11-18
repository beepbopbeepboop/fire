#!/usr/bin/env python3
"""land_doc must not file a doc that cites a deleted bug doc: the doc-refs ratchet goes red the
moment such a doc lands, because a brand-new file has a 0 ceiling and the citation is a GAIN
(2026-11-17, observed on master b531a4f6a while landing the cases-generator analyzer branch: the
land doc for a task whose summary named a doc deleted by the round that fixed it).

The task summary quotes the worker's task file, which names the bug doc as `bugs/<name>.md`. When
the branch being landed IS the fix, that doc has already been deleted, so the `**Original work:**`
line land_doc used to write verbatim was a dangling citation from birth. land_doc now sanitizes the
summary (`dangling_doc_refs.sanitize_text`): a citation of a doc this tree no longer has becomes
the bare stem plus "(deleted)", in BOTH ratchet classes -- the `bugs/`-prefixed walk in `find()`
has no deleted-word skip, so the path must come out of the text, not just be annotated -- and a
citation that resolves is left alone.

The fixture names are built by concatenation so this file's own source carries no literal
`bugs/<name>.md` or `<STEM>.md` citation of a doc that is nowhere in the tree (the doc-refs
ratchet walks this file; `test_integrate_dryrun.py` splits its fixture the same way).

Run: python3 tools/test_land_doc_summary.py
"""
import os, subprocess, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I
import dangling_doc_refs as DDR

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(d, *a):
    subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, text=True, env=ENV)

# One deleted name per ratchet class, and one LIVE name per class that the sanitize must leave
# untouched (a sanitizer that rewrites what resolves is a sweep, not a fix).
GONE_PREFIXED = "bugs/" + "GONE_doc_2026_11_17" + ".md"    # the spelling the worker's task file uses
GONE_BARE = "GONE_DOC_BARE" + ".md"                        # the spelling the bare class walks
LIVE_PREFIXED = "bugs/" + "OPEN_doc" + ".md"               # present in the throwaway bugs/
LIVE_BARE = "NOTE_keep" + ".md"                            # present at the throwaway root


def _summary():
    return ("Fix the bug in `%s` at its ROOT CAUSE (see also `%s`), "
            "alongside the live `%s` and the note `%s`"
            % (GONE_PREFIXED, GONE_BARE, LIVE_PREFIXED, LIVE_BARE))


def _file_land_doc(d, within=None):
    """Run land_doc against the throwaway tree `d`: both `control.MAIN` (where the doc is written
    and the branch is read) and `dangling_doc_refs.ROOT` (where the sanitize and the ratchet walk
    resolve existence) point at it, so one tree answers both questions. commit_doc is mocked (the
    real one commits through the fleet's git identity and exits if MAIN is not a repository root)
    and branch_age stubbed for a stable body. `within` is an optional callable run while the mocks
    hold -- the ratchet walk, which must resolve existence in the SAME throwaway tree, not the one
    this test was started in."""
    t = {"branch": "work/bug-x", "summary": _summary(), "claims": ["bug:X"]}
    with mock.patch.object(C, "MAIN", d), mock.patch.object(DDR, "ROOT", d), \
         mock.patch.object(I, "commit_doc"), \
         mock.patch.object(I, "branch_age", return_value="last commit 2026-11-17; 1 commit(s) ahead of master, 0 behind it"):
        p = I.land_doc("bug-x", t, "conflicts with master")
        if within:
            within()
        return p


class LandDocSummarySanitized(unittest.TestCase):
    def test_deleted_citations_are_rewritten_and_live_ones_survive(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "bugs"))
            open(os.path.join(d, "bugs", "OPEN_doc" + ".md"), "w").write("# open\n")
            open(os.path.join(d, "NOTE_keep" + ".md"), "w").write("# note\n")
            body = open(_file_land_doc(d)).read()
            self.assertNotIn(GONE_PREFIXED, body)      # the prefixed path is OUT of the text
            self.assertNotIn(GONE_BARE, body)          # ... and so is its bare spelling
            self.assertIn("GONE_doc_2026_11_17 (deleted)", body)
            self.assertIn("GONE_DOC_BARE (deleted)", body)
            self.assertIn(LIVE_PREFIXED, body)         # a citation that resolves is left alone
            self.assertIn(LIVE_BARE, body)

    def test_ratchet_stays_green_on_the_filed_doc(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "bugs"))
            open(os.path.join(d, "bugs", "OPEN_doc" + ".md"), "w").write("# open\n")
            open(os.path.join(d, "NOTE_keep" + ".md"), "w").write("# note\n")
            # The throwaway is a STANDALONE repository, not a scratch dir inside this worktree:
            # `candidates()` walks `git ls-files`, and a scratch dir inside a worktree would list
            # the ENCLOSING tree's index (through `../..` paths) instead of the throwaway's own.
            # Production shape, too: the integrator commits the doc before the ratchet walks it.
            g(d, "init", "-q", "-b", "master"); g(d, "add", "."); g(d, "commit", "-q", "-m", "root")
            seen = {}

            def within():
                # commit the filed doc the way the integrator does, then walk it while the mocks hold
                g(d, "add", "."); g(d, "commit", "-q", "-m", "filed")
                _have, _by_doc, by_file = DDR.find()
                _bare_doc, bare_by_file = DDR.bare_find()
                seen["by_file"], seen["bare_by_file"] = by_file, bare_by_file
                seen["verdict"] = DDR.ratchet_verdict(by_file, bare_by_file,
                                                      baseline={}, bare_baseline={})

            p = _file_land_doc(d, within=within)
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            by_file, bare_by_file = seen["by_file"], seen["bare_by_file"]
            # The two walks feed the ratchet: a brand-new file has a 0 ceiling in both ledgers, so
            # ANY citation it carries is a regression. The filed doc must carry none.
            self.assertEqual(by_file.get(rel, ()), (),
                             "%s gained a `bugs/`-prefixed citation of a deleted doc: %r"
                             % (rel, by_file.get(rel)))
            self.assertEqual(bare_by_file.get(rel, ()), (),
                             "%s gained a bare citation of a doc that is nowhere: %r"
                             % (rel, bare_by_file.get(rel)))
            # The ratchet's whole verdict in one call, judged against 0 ceilings: nothing in the
            # throwaway may appear among the regressions in either class.
            prefixed, bare = seen["verdict"]
            self.assertEqual([r for r, *_ in prefixed], [], "prefixed regressions: %r" % (prefixed,))
            self.assertEqual([r for r, *_ in bare], [], "bare regressions: %r" % (bare,))


if __name__ == "__main__":
    unittest.main()
