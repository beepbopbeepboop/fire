#!/usr/bin/env python3
"""Regression: a required trait method implemented by two conditional overloads
(`where conforms_to(Self.T, X)`), one provably valid from the struct's own
evidence (bound `T: Movable` plus the trait base's `where conforms_to(T,
Copyable)`) and one needing evidence that is not there, cannot be selected:
`ambiguous reference to 'handle': lacking evidence to select candidate`, with the
candidate, constraint, `provide evidence`, `required by trait method` and trait
notes, and the struct named with its parameters (`S[T]`). Expected text captured
from `tools/mojo build -I` (DIAGNOSTICS_formatting_modular part 1, group K)."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

PACKAGE = 'trait UnprovableCandidateTrait:\n    def handle(self):\n        ...\n'

MAIN = 'import pk\n\n\nstruct UnprovableWithValidCandidate[T: Movable](\n    Movable,\n    pk.UnprovableCandidateTrait where conforms_to(T, Copyable),\n):\n    def handle(self) where conforms_to(Self.T, Intable):\n        pass\n\n    def handle(self) where conforms_to(Self.T, Copyable):\n        pass\n\n\ndef main():\n    print("must not run")\n'

WANT = "M:4:8: error: 'UnprovableWithValidCandidate[T]' does not implement all requirements for 'UnprovableCandidateTrait'\nstruct UnprovableWithValidCandidate[T: Movable](\n       ^\nImported from M:1:\nP:2:9: note: ambiguous reference to 'handle': lacking evidence to select candidate\n    def handle(self):\n        ^\nM:8:9: note: cannot prove constraint for candidate\n    def handle(self) where conforms_to(Self.T, Intable):\n        ^\nM:8:28: note: constraint declared here needs evidence for 'conforms_to(T, Intable)'\n    def handle(self) where conforms_to(Self.T, Intable):\n                           ^\nM:11:9: note: candidate is valid but cannot be selected until other candidates are disproved\n    def handle(self) where conforms_to(Self.T, Copyable):\n        ^\nM:4:8: note: provide evidence for or against the constraints here to aid in candidate selection\nstruct UnprovableWithValidCandidate[T: Movable](\n       ^\nImported from M:1:\nP:2:9: note: required by trait method here\n    def handle(self):\n        ^\nImported from M:1:\nP:1:7: note: trait 'UnprovableCandidateTrait' declared here\ntrait UnprovableCandidateTrait:\n      ^\n"


def test_ambiguous_candidate_selection():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'pk'))
        pk = os.path.join(d, 'pk', '__init__.mojo')
        open(pk, 'w').write(PACKAGE)
        m = os.path.join(d, 'k.mojo')
        open(m, 'w').write(MAIN)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(pk, 'P').replace(m, 'M')
        assert p.returncode == 1 and p.stdout == '' and err == WANT, err


if __name__ == '__main__':
    test_ambiguous_candidate_selection()
    print('ok test_ambiguous_candidate_selection')
    print('all tests passed')
