#!/usr/bin/env python3
"""Regression: the static trait checks follow a module's imports. A struct whose
trait base comes from a package beside the file (`diags_package.T`) is checked
exactly like a same-module trait, and each note from the package is introduced
by `Imported from <file>:<line>:`. Expected text captured from `tools/mojo build
-I` on the same sources (DIAGNOSTICS_formatting_modular part 1, groups H-L).
The package is the trait part of modular's test/mojo-integration/inputs/
diags_package."""
import os
import subprocess
import sys
import tempfile

FIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fire.py')

PACKAGE = 'trait ConflictTraitName:\n    def test[a: Int](self):\n        pass\n\n\ntrait NoDefaultFunc:\n    def doSomething(self):\n        ...\n\n\ntrait StillNoDefaultFunc(NoDefaultFunc):\n    def doEverything(self):\n        ...\n\n\ntrait UnprovableCandidateTrait:\n    # expected-note @below {{required by trait method here}}\n    def handle(self):\n        ...\n\n\ntrait ConflictTraitMethod:\n    def test(self) -> Bool:\n        return True\n\n\ntrait OtherConflictTraitMethod(ConflictTraitMethod):\n    def test(self) -> Bool:\n        return False\n\n\ntrait TraitWithMember:\n    comptime N: Int\n'

MAIN = 'import diags_package\n\n\nstruct ConflictStruct[a: Int](diags_package.ConflictTraitName):\n    pass\n\n\nstruct ConflictMethod(diags_package.OtherConflictTraitMethod):\n    pass\n\n\nstruct StructViolation(diags_package.StillNoDefaultFunc):\n    def doEverything(self):\n        pass\n\n\nstruct NoAlias(diags_package.TraitWithMember):\n    pass\n\n\nstruct Mismatched(diags_package.TraitWithMember):\n    comptime N: Bool = Bool()\n\n\ndef main():\n    pass\n'

WANT = "M:4:8: error: name conflict between parameter 'a' in the default trait method and a parameter in the struct\nstruct ConflictStruct[a: Int](diags_package.ConflictTraitName):\n       ^\nImported from M:1:\nP:2:9: note: trait method declared here\n    def test[a: Int](self):\n        ^\nM:8:8: error: trait method requirement 'test' has conflicting default implementations in 'ConflictTraitMethod' and 'OtherConflictTraitMethod'; you must implement it manually\nstruct ConflictMethod(diags_package.OtherConflictTraitMethod):\n       ^\nImported from M:1:\nP:23:9: note: original default implementation from trait 'ConflictTraitMethod' here\n    def test(self) -> Bool:\n        ^\nImported from M:1:\nP:28:9: note: conflicting implementation from trait 'OtherConflictTraitMethod' here\n    def test(self) -> Bool:\n        ^\nM:12:8: error: 'StructViolation' does not implement all requirements for 'NoDefaultFunc'\nstruct StructViolation(diags_package.StillNoDefaultFunc):\n       ^\nImported from M:1:\nP:7:9: note: required function 'doSomething' is not implemented\n    def doSomething(self):\n        ^\nImported from M:1:\nP:6:7: note: trait 'NoDefaultFunc' declared here\ntrait NoDefaultFunc:\n      ^\nM:17:8: error: 'NoAlias' does not implement all requirements for 'TraitWithMember'\nstruct NoAlias(diags_package.TraitWithMember):\n       ^\nImported from M:1:\nP:33:5: note: required member 'N' is not specified\n    comptime N: Int\n    ^\nImported from M:1:\nP:32:7: note: trait 'TraitWithMember' declared here\ntrait TraitWithMember:\n      ^\nM:21:8: error: 'Mismatched' does not implement all requirements for 'TraitWithMember'\nstruct Mismatched(diags_package.TraitWithMember):\n       ^\nImported from M:1:\nP:33:5: note: comptime member 'N' type 'Bool' does not conform to trait's required type 'Int'\n    comptime N: Int\n    ^\nImported from M:1:\nP:32:7: note: trait 'TraitWithMember' declared here\ntrait TraitWithMember:\n      ^\n"


def test_traits_imported_from_a_package():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'diags_package'))
        pk = os.path.join(d, 'diags_package', '__init__.mojo')
        open(pk, 'w').write(PACKAGE)
        m = os.path.join(d, 'p.mojo')
        open(m, 'w').write(MAIN)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(pk, 'P').replace(m, 'M')
        assert p.returncode == 1 and err == WANT, err


if __name__ == '__main__':
    test_traits_imported_from_a_package()
    print('ok test_traits_imported_from_a_package')
    print('all tests passed')
