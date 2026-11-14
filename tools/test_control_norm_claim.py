#!/usr/bin/env python3
"""control.norm_claim: every spelling of one bug document is one `bug:<name>` claim, whatever class directory it sits in.

A bare name, a name with `.md`, `bugs/<name>.md` and `bugs/<class>/<name>.md` (the swarm moves documents between class
directories, e.g. `bugs/mid/`) must all normalise to the same key, so that `conflicts` admits one holder for one
document. A path it does not recognise must be refused, not passed through as a literal claim that conflicts with
nothing.

Run: python3 tools/test_control_norm_claim.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C

STEM = "FORMAL_arm64_instruction_coverage"


def test_every_spelling_of_one_document_is_one_claim():
    """Bare, .md, bugs/, bugs/hard/ and bugs/mid/ spellings all normalise to bug:<stem>."""
    spellings = [STEM, STEM + ".md", "bugs/" + STEM + ".md", "bugs/hard/" + STEM + ".md",
                 "bugs/mid/" + STEM + ".md"]
    got = [C.norm_claim(s) for s in spellings]
    assert all(g == "bug:" + STEM for g in got), got


def test_class_directory_spelling_conflicts_with_bare_claim():
    """A worker holding bug:<stem> blocks a claim spelled with the class directory, and vice versa."""
    held = "bug:" + STEM
    moved = C.norm_claim("bugs/mid/" + STEM + ".md")
    assert C.conflicts(moved, held), (moved, held)
    assert C.conflicts(held, moved), (held, moved)


def test_non_bug_claim_keys_pass_through():
    """Keys that already carry a namespace (bug:, gate:, ...) are returned unchanged."""
    for key in ["bug:" + STEM, "gate:stdlib-dylib", "gate:bootstrap-stage1-dumps:fire_compiler.py"]:
        assert C.norm_claim(key) == key, key


def test_unrecognised_path_is_refused():
    """A path the normaliser cannot place is an error, not a literal claim that conflicts with nothing."""
    for bad in ["bugs/mid/sub/" + STEM + ".md", "src/foo.py", "bugs/mid/ x.md"]:
        try:
            got = C.norm_claim(bad)
        except ValueError:
            continue
        raise AssertionError("norm_claim(%r) returned %r instead of refusing" % (bad, got))


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    print("FAILED" if failed else "OK")
    sys.exit(1 if failed else 0)
