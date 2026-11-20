#!/usr/bin/env python3
"""Regression: x86 end-to-end value facts cite the fork state's hval.

formal.x86_64_endtoend_test used to index the predecessor value fact by
global step index (`hval{k-1}`), so the first step of a by_cases arm
after a fork cited the other arm's last `hval`, which was out of scope in
that arm (Unknown identifier + free-variable cascade). The emitter must
instead cite the fork state's value fact (`hval_base`) for steps that
start from the fork state.

Measured case: multi_export (arm 1 first fact hval42 must cite hval36, not
hval41). Without the fix the generated simp cites the other arm's last hval.
(The branch also pinned pair's hval27 -> hval21; master no longer emits a
hval27 for pair, so that pin named an older base's numbering and is dropped.)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from formal import x86_64_endtoend_test as T


def _first_value_fact_simp(text, have_name):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("have " + have_name + " "):
            # the fact's proof is a `simp [...]` line following the have.
            for j in range(i + 1, min(i + 20, len(lines))):
                stripped = lines[j].strip()
                if stripped.startswith("simp ["):
                    return stripped
            raise AssertionError("no simp found after " + have_name)
    raise AssertionError("value fact not found: " + have_name)


def main():
    cases = [
        ("formal/examples/multi_export.mojo", "hval42", "hval36", "hval41"),
    ]
    for path, have_name, good, bad in cases:
        text = T.emit_terminates(os.path.join(HERE, path))
        simp = _first_value_fact_simp(text, have_name)
        assert good in simp, (
            "%s: %s must cite fork-state fact %s, got: %s"
            % (path, have_name, good, simp))
        assert bad not in simp, (
            "%s: %s must not cite other arm's last fact %s, got: %s"
            % (path, have_name, bad, simp))
        print("ok", path, have_name, "->", simp)
    print("PASS")


if __name__ == "__main__":
    main()
