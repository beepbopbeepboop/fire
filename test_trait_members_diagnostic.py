#!/usr/bin/env python3
"""Regression: the static trait checks that run before execution, each case's
expected text captured from `tools/mojo build` on the same source
(DIAGNOSTICS_formatting_modular part 1, groups H, I, L and the phase order):

* H  a struct bracket parameter that a DEFAULT trait method also declares;
* I  a method with default implementations in two traits, not implemented;
* L  a required `comptime` member that is missing or has the wrong type
     (member and function notes interleave in the trait's declaration order);
* a struct gets the errors of the FIRST phase (H, then I, then unmet
  requirements) that finds any; a trait's own default `comptime` member is not
  a requirement."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')


def run(src):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 't.mojo')
        open(f, 'w').write(src)
        p = subprocess.run([sys.executable, FIRE, 'run', f],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stderr.replace(f, 'F')


CASES = {
    'h': (
        'trait ConflictTraitName:\n    def test[a: Int](self):\n        pass\n\n\nstruct ConflictStruct[a: Int](ConflictTraitName):\n    pass\n\n\ntrait ConflictTraitMethod:\n    def test(self) -> Bool:\n        return True\n\n\ntrait OtherConflictTraitMethod(ConflictTraitMethod):\n    def test(self) -> Bool:\n        return False\n\n\nstruct ConflictMethod(OtherConflictTraitMethod):\n    pass\n\n\ntrait TraitWithMember:\n    comptime N: Int\n\n\nstruct NoAlias(TraitWithMember):\n    pass\n\n\nstruct Mismatched(TraitWithMember):\n    comptime N: Bool = Bool()\n\n\nstruct SameName(TraitWithMember):\n    var N: Int\n\n\nstruct Good(TraitWithMember):\n    comptime N: Int = 3\n\n\ndef main():\n    pass\n',
        "F:6:8: error: name conflict between parameter 'a' in the default trait method and a parameter in the struct\nstruct ConflictStruct[a: Int](ConflictTraitName):\n       ^\nF:2:9: note: trait method declared here\n    def test[a: Int](self):\n        ^\nF:20:8: error: trait method requirement 'test' has conflicting default implementations in 'ConflictTraitMethod' and 'OtherConflictTraitMethod'; you must implement it manually\nstruct ConflictMethod(OtherConflictTraitMethod):\n       ^\nF:11:9: note: original default implementation from trait 'ConflictTraitMethod' here\n    def test(self) -> Bool:\n        ^\nF:16:9: note: conflicting implementation from trait 'OtherConflictTraitMethod' here\n    def test(self) -> Bool:\n        ^\nF:28:8: error: 'NoAlias' does not implement all requirements for 'TraitWithMember'\nstruct NoAlias(TraitWithMember):\n       ^\nF:25:5: note: required member 'N' is not specified\n    comptime N: Int\n    ^\nF:24:7: note: trait 'TraitWithMember' declared here\ntrait TraitWithMember:\n      ^\nF:32:8: error: 'Mismatched' does not implement all requirements for 'TraitWithMember'\nstruct Mismatched(TraitWithMember):\n       ^\nF:25:5: note: comptime member 'N' type 'Bool' does not conform to trait's required type 'Int'\n    comptime N: Int\n    ^\nF:24:7: note: trait 'TraitWithMember' declared here\ntrait TraitWithMember:\n      ^\nF:36:8: error: 'SameName' does not implement all requirements for 'TraitWithMember'\nstruct SameName(TraitWithMember):\n       ^\nF:25:5: note: required member 'N' is not specified\n    comptime N: Int\n    ^\nF:24:7: note: trait 'TraitWithMember' declared here\ntrait TraitWithMember:\n      ^\n"),
    'c': (
        'trait T1:\n    comptime N: Int\n    comptime M: Int\n\n    def need(self):\n        ...\n\n    def dflt[a: Int](self):\n        pass\n\n\nstruct S[a: Int](T1):\n    comptime M: Bool = Bool()\n\n\ntrait WithDefault:\n    comptime K: Int = 5\n\n\nstruct U(WithDefault):\n    pass\n\n\ndef main():\n    pass\n',
        "F:12:8: error: name conflict between parameter 'a' in the default trait method and a parameter in the struct\nstruct S[a: Int](T1):\n       ^\nF:8:9: note: trait method declared here\n    def dflt[a: Int](self):\n        ^\n"),
    'c2': (
        'trait C1:\n    def test(self) -> Bool:\n        return True\n\n\ntrait C2(C1):\n    comptime N: Int\n\n    def test(self) -> Bool:\n        return False\n\n    def need(self):\n        ...\n\n\nstruct S(C2):\n    pass\n\n\ntrait L1:\n    comptime N: Int\n\n    def need(self):\n        ...\n\n\nstruct V(L1):\n    pass\n\n\ndef main():\n    pass\n',
        "F:16:8: error: trait method requirement 'test' has conflicting default implementations in 'C1' and 'C2'; you must implement it manually\nstruct S(C2):\n       ^\nF:2:9: note: original default implementation from trait 'C1' here\n    def test(self) -> Bool:\n        ^\nF:9:9: note: conflicting implementation from trait 'C2' here\n    def test(self) -> Bool:\n        ^\nF:27:8: error: 'V' does not implement all requirements for 'L1'\nstruct V(L1):\n       ^\nF:21:5: note: required member 'N' is not specified\n    comptime N: Int\n    ^\nF:23:9: note: required function 'need' is not implemented\n    def need(self):\n        ^\nF:20:7: note: trait 'L1' declared here\ntrait L1:\n      ^\n"),
}


def _check(name):
    src, want = CASES[name]
    rc, err = run(src)
    assert rc == 1 and err == want, err


def test_name_conflict_conflicting_defaults_and_members():
    _check('h')


def test_first_phase_wins_name_conflict_over_unmet_requirements():
    _check('c')


def test_first_phase_wins_conflicting_defaults_and_member_before_function_notes():
    _check('c2')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
    print('all tests passed')
