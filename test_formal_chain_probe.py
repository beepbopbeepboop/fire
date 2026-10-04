#!/usr/bin/env python3
"""Does the chain probe name the module that refused, so it can walk the chain?

`tools/formal_chain_probe.py` exists to answer a question `tools/formal_sweep.py`
structurally cannot: the sweep reports ONE link per file, the first refusal its
build walk reaches, so "FILES BLOCKED IS AN UPPER BOUND" — fixing one cause
moves a file to the next with the count unchanged. The probe walks the rest, one
link per round, by rewriting the refusing module in a throwaway copy of the
stdlib and asking again.

It could not do that for the tree's single largest cause. Measured 2026-10-04 on
`std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}`
(`bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §1), round 0 of a
46-file scope reported

    === round 0: 3 built, 3 refusing module(s)
       37  <no module named>
        4  _io.mojo
        2  constants.mojo

  (stopping: <no module n is not under the stdlib copy, so there is nothing this
   tool may rewrite)

— 37 of 46 files grouped under a placeholder, and then the walk STOPPED, because
the victim is chosen by sorting the group keys and the placeholder is not a
filename. So the instrument reported *no chain at all* for the refusal that
blocks the most files, and named a nonsense module (`<no module n` is the
placeholder with five characters sliced off, as if it were a `.mojo` stem).

The cause is that there are TWO shapes of "module X refused", and only the first
was recognised. `formal/build.py`'s chain wrapper names the refusing file in a
`<file>: ` prefix. `formal/model.py::imported_callee_refusal` — what a call to a
name the DEFINING module does not export produces, and the single largest cause
in the tree at 123 files — names it in prose instead, and fell into the
catch-all.

Nothing here builds a program or runs Lean. The units are the two message shapes,
the resolution, and the choice of which group to rewrite next.

    python3 test_formal_chain_probe.py [-v]
"""
import importlib.util
import os
import pathlib
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

_spec = importlib.util.spec_from_file_location(
    "formal_chain_probe", os.path.join(HERE, "tools", "formal_chain_probe.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

STDLIB = pathlib.Path(
    os.environ.get("MOJO_STDLIB")
    or (pathlib.Path(HERE).parent / "new-modular" / "Mojo" / "stdlib")
).resolve()

# The six refusals a 46-file `std/{os,io,pathlib,hashlib,base64,ffi,python,_gpu}`
# scope answered with on 2026-10-04, one per refusing module, VERBATIM from
# `bugs/sweeps/`. The first is the chain wrapper (which the probe always read);
# the other five are `imported_callee_refusal`, whose module is named in prose.
# Each is pinned with the file that produced it, because the module name is
# resolved RELATIVE TO THE IMPORTER and that is half of what is being tested:
# `..fstat` is `std/os/fstat.mojo` from `std/os/path/path.mojo` and nothing at
# all from `std/ffi/__init__.mojo`.
CHAIN_PREFIX = (
    "build: __init__.mojo imports 'std.sys', which cannot be built either: "
    "_io.mojo: formal dylib has no public functions: _io.mojo exports nothing "
    "under doc/ABI.md's rules because it declares no function and no type at "
    "all",
    "std/os/fstat.mojo",
    "_io.mojo",
)

EXPORT_GATE = {
    "std/memory/alloc.mojo": (
        "std/ffi/__init__.mojo",
        "build: `dealloc` is called, and it is imported from `std.memory.alloc`, "
        "so the call has to bind a symbol `std.memory.alloc` exports. That "
        "module does not export it, and the reason is `doc/ABI.md`'s export "
        "rule rather than anything about this call: a name with a leading `_` "
        "is private, a generic template is not one symbol but one per "
        "instantiation",
    ),
    "std/format/_utils.mojo": (
        "std/ffi/unsafe_union.mojo",
        "build: `FormatStruct` is called, and it is imported from "
        "`std.format._utils`, so the call has to bind a symbol "
        "`std.format._utils` exports. That module does not export it",
    ),
    "std/bit/mask.mojo": (
        "std/base64/_b64encode.mojo",
        "build: log2_floor: `is_negative` is called, and it is imported from "
        "`std.bit.mask`, so the call has to bind a symbol `std.bit.mask` "
        "exports. That module does not export it",
    ),
    # A PACKAGE, not a module file: `std.math` is `std/math/__init__.mojo`, and
    # its stem is `__init__` — which is the case that makes the exact path
    # necessary rather than merely tidier (see TestStubTargets).
    "std/math/__init__.mojo": (
        "std/_gpu/__init__.mojo",
        "build: ualign_up: `align_up` is called, and it is imported from "
        "`std.math`, so the call has to bind a symbol `std.math` exports. That "
        "module does not export it",
    ),
    # A RELATIVE spelling, resolved against the importing file's directory.
    "std/os/fstat.mojo": (
        "std/os/path/path.mojo",
        "build: getsize: `stat` is called, and it is imported from `..fstat`, "
        "so the call has to bind a symbol `..fstat` exports. That module does "
        "not export it",
    ),
}


def _rel(probe):
    return lambda p: P.under_stdlib(pathlib.Path(p), probe)


@unittest.skipUnless(STDLIB.is_dir(), f"no stdlib at {STDLIB}")
class TestRefusingModule(unittest.TestCase):
    """The two shapes name a module, and the export-gate one names it exactly."""

    def setUp(self):
        self.probe = pathlib.Path(HERE) / ".tmp" / "chain-probe-test"
        shutil.rmtree(self.probe, ignore_errors=True)
        shutil.copytree(STDLIB, self.probe)

    def tearDown(self):
        shutil.rmtree(self.probe, ignore_errors=True)

    def _name(self, msg, importer):
        key, _exact, stem = P.refusing_module(
            msg, self.probe / importer, _rel(self.probe), self.probe)
        return key, stem

    def test_the_chain_prefix_still_names_its_bare_basename(self):
        """The shape that worked before, unchanged.

        It keeps the basename and no exact path, because a basename like
        `stat.mojo` is ambiguous in this tree (a stdlib package AND a hostmod)
        and searching the copy for it is what this tool has always done.
        """
        msg, importer, want = CHAIN_PREFIX
        self.assertEqual(self._name(msg, importer), (want, want[:-len(".mojo")]))

    def test_every_measured_export_gate_refusal_names_its_module(self):
        """The 37-of-46 group, one refusing module at a time.

        Each expectation is the FILE, not the module name: the probe has to
        rewrite a file, and `std.math` is a directory full of `__init__.mojo`
        whose basename is the least identifying string in the tree.
        """
        for want_file, (importer, msg) in EXPORT_GATE.items():
            with self.subTest(module=want_file):
                key, _stem = self._name(msg, importer)
                self.assertEqual(key, want_file)

    def test_an_unrecognised_message_is_still_the_catch_all(self):
        """A wording this tool does not know keeps its own bucket.

        `<no module named>` is not a filename and must not become one: that is
        the bug whose symptom was a walk that stopped at round 0.
        """
        key, stem = self._name("build: something entirely unrecognised",
                               "std/os/fstat.mojo")
        self.assertEqual(key, P.NO_MODULE)
        self.assertEqual(stem, "")

    def test_a_relative_module_name_is_relative_to_the_IMPORTER(self):
        """`..fstat` has two answers and only one of them is the module.

        This is why the probe passes the importing path in: resolving a
        relative spelling against the stdlib root (or against the message, which
        does not say who is importing) picks a different file, and the walk then
        rewrites a module nothing in the chain refused.
        """
        msg = EXPORT_GATE["std/os/fstat.mojo"][1]
        self.assertEqual(self._name(msg, "std/os/path/path.mojo")[0],
                         "std/os/fstat.mojo")
        _key, _exact, stem = P.refusing_module(
            msg, self.probe / "std/ffi/__init__.mojo", _rel(self.probe),
            self.probe)
        self.assertIsNone(_exact,
                          "`..fstat` from std/ffi resolves to nothing, so the "
                          "group must stay unrewritable rather than guess")
        self.assertEqual(stem, "fstat")

    def test_a_module_outside_the_copy_is_not_a_target(self):
        """THE REAL STDLIB IS ONLY EVER READ, and this is where that is enforced.

        The scope this tool takes by default is this repository's own `*.py`,
        which is measured against ITSELF and never rewritten — and for such an
        importer the resolver's answer is a path in the real stdlib. That path
        EXISTS, so an `is_file()` check passes, and the next thing the walk does
        is `write_text` over it. The measured run this fix came from had exactly
        that shape available to it.
        """
        real = STDLIB / "std" / "format" / "_utils.mojo"
        self.assertTrue(real.is_file(), "the real stdlib must be where it says")
        importer = pathlib.Path(HERE) / "tools" / "formal_chain_probe.py"
        _key, exact, stem = P.refusing_module(
            EXPORT_GATE["std/format/_utils.mojo"][1], importer,
            _rel(self.probe), self.probe)
        self.assertIsNone(exact,
                          f"a path outside the copy must not be actionable, or "
                          f"the stub step writes the real stdlib ({real})")
        self.assertEqual(stem, "_utils",
                         "the basename half of the answer is still available, "
                         "and `stub_targets` will look for it INSIDE the copy")


@unittest.skipUnless(STDLIB.is_dir(), f"no stdlib at {STDLIB}")
class TestStubTargets(unittest.TestCase):
    """What gets rewritten: exactly the file that refused, or nothing."""

    def setUp(self):
        self.probe = pathlib.Path(HERE) / ".tmp" / "chain-probe-test"
        shutil.rmtree(self.probe, ignore_errors=True)
        shutil.copytree(STDLIB, self.probe)

    def tearDown(self):
        shutil.rmtree(self.probe, ignore_errors=True)

    def _targets(self, msg, importer):
        key, exact, stem = P.refusing_module(
            msg, self.probe / importer, _rel(self.probe), self.probe)
        return key, P.stub_targets(
            {"exact": exact, "stem": stem, "members": []}, self.probe)

    def test_an_exact_module_resolves_to_exactly_one_file(self):
        """Including a package, whose stem would rewrite the whole tree.

        `__init__` is the stem of `std/math/__init__.mojo`, and the copy holds
        one `__init__.mojo` per package. Stubbing by stem there replaces every
        package in the stdlib, which is not a shorter chain — it is a different
        measurement.
        """
        msg = EXPORT_GATE["std/math/__init__.mojo"][1]
        key, targets = self._targets(msg, "std/_gpu/__init__.mojo")
        self.assertEqual(key, "std/math/__init__.mojo")
        self.assertEqual([str(t) for t in targets],
                         [str(self.probe / "std" / "math" / "__init__.mojo")])
        self.assertGreater(len(list(self.probe.rglob("__init__.mojo"))), 1,
                           "the stdlib copy must still hold several packages, "
                           "or this case proves nothing")

    def test_the_catch_all_group_has_nothing_to_rewrite(self):
        """`stub_targets` returning [] is what lets the walk move on.

        The main loop skips a group with no target and picks the first group
        that has one; a tool that instead tried to rewrite the placeholder
        sliced as a filename is what stopped the walk at round 0.
        """
        self.assertEqual(
            P.stub_targets({"exact": None, "stem": "", "members": []},
                           self.probe),
            [])

    def test_a_bare_basename_still_searches_the_copy(self):
        """The chain-prefix shape's behaviour, unchanged."""
        msg, importer, _want = CHAIN_PREFIX
        _key, targets = self._targets(msg, importer)
        self.assertTrue(targets, "a basename group must find its file(s)")
        self.assertTrue(all(t.name == "_io.mojo" for t in targets))


@unittest.skipUnless(STDLIB.is_dir(), f"no stdlib at {STDLIB}")
class TestMangledCopy(unittest.TestCase):
    """The tool's OWN damage is not a link in the chain.

    Round 4 of the measured run answered `build: 32:0: Unexpected INDENT('')`
    for all 42 remaining files in a 46-file scope, and the round was about to be
    reported as one link blocking 42 files. It is one mangled file: the stub step
    dropped an import line that was the only statement in an indented block, and
    every file importing that module reported the parser's complaint in its own
    build. Grouping those 42 under a construct refusal is precisely the mistake
    this tool exists to prevent, one level up from where it usually happens.
    """

    # Verbatim from the run: `build: 32:0: Unexpected INDENT('')`.
    MEASURED = "build: 32:0: Unexpected INDENT('')"

    def test_a_parse_error_in_the_copy_is_recognised(self):
        self.assertTrue(P.mangled_copy(self.MEASURED))

    def test_the_three_spellings_are_recognised(self):
        for msg in ("build: x.mojo:12:3: IndentationError: unindent does not "
                    "match any outer indentation level",
                    "  File \"x.mojo\", line 9\n    unexpected indent",
                    "build: expected an indented block after 'if' on line 4"):
            with self.subTest(msg=msg):
                self.assertTrue(P.mangled_copy(msg))

    def test_a_real_refusal_is_not_taken_for_one(self):
        """Every message the measured scope actually produced stays a link.

        Pinned so the recogniser cannot widen: a refusal is a claim about a
        construct, and this tool's job is to report those, not to discard the
        awkward ones.
        """
        for msg in [m[1] for m in EXPORT_GATE.values()] + [CHAIN_PREFIX[0]]:
            with self.subTest(msg=msg[:60]):
                self.assertFalse(P.mangled_copy(msg))

    def test_a_timeout_is_not_a_mangled_copy(self):
        self.assertFalse(P.mangled_copy(f"TIMEOUT after {P.BUILD_TIMEOUT}s"))


if __name__ == "__main__":
    unittest.main()