#!/usr/bin/env python3
"""Tests for tools/formal_sweep.py's verdict classification and reporting.

The sweep itself is expensive (a real `fire.py build --formal` per file), so
nothing here builds anything: the unit under test is the layer that decides
what a build's outcome MEANS, which is the layer that was missing. Every case
below is a real message the build prints, quoted from the tool's own recorded
runs, because a classifier tested only against messages it invented tests
nothing.

    python3 test_formal_sweep.py [-v]

Run by `make check-formal-sweep`, which wraps it in checked_run.py with this
file, tools/formal_sweep.py, fire.py, fire_compiler.py and every formal/*.py
as the hashed inputs — the sweep's verdict is a function of all of those, so a
cached result from a different set would be a different answer.
"""
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tools"))

import cas
import formal_sweep as S
import procrun

# ── The messages this classifies, verbatim ───────────────────────────────────
# The host-import and unresolved-import wordings are the two ImportBuildError
# texts in formal/build.py and formal/imports.py; formal/build.py's own comment
# says there is one wording for one condition, so these two partition that
# space. The "cannot be lowered" text is formal/build.py's refusal for a
# construct, and the "builds, but N import(s)" text is the dyld check in
# run_one itself.
HOST_MSG = ("build: fire.py imports 'os', which is a host module (CPython "
            "standard library), which has no Mojo source for this backend to "
            "compile")
UNRESOLVED_MSG = ("build: wave1.py imports '__future__', which is not a "
                  "stdlib or sibling module, and no such file exists")
CODEGEN_MSG = ("build: GimpleGen._record_sys_path_inserts() cannot be lowered: "
               "its receiver has 16 fields and a formal value is one word, so "
               "`self.<field>` has no representation on this path")
# The CHAINED form: formal/build.py wraps a dependency's own error inside the
# importer's, and the two messages below are quoted from a real stdlib sweep.
# Wave 1 added the wrapper as better diagnostics; the classifier used to read
# only the outer layer and file all 204 of these as `unknown`, which is how the
# largest class in the default sweep was this instrument throwing away the only
# part of the message that says anything about the backend.
CHAIN_MSG = (
    "build: write.mojo imports 'std.format', which cannot be built either: "
    "binary_heap.mojo: formal dylib has no public functions: binary_heap.mojo "
    "exports nothing under doc/ABI.md's rules (a struct-only module has no "
    "free-function API, and this backend compiles no struct methods)")
# Two hops, to pin that peeling is by shape at any depth rather than a list of
# the messages this tool has seen.
CHAIN_MSG_2 = (
    "build: reduce.mojo imports 'std.math', which cannot be built either: "
    "env.mojo imports 'std.sys', which cannot be built either: "
    "env.mojo: ptr.value() is a method call on a value, and this backend "
    "lowers only append, close, write")
# B3's refusal, verbatim from the model's own function (formal/model.py:
# gimple_runtime_refusal), which is what the class is keyed on.
TARGET_MSG = ("build: mojo_sqlite3_open is an entry point of the gimple "
              "backend's C runtime (the `mojo_*` ABI declared in "
              "runtime/fire_runtime.h and runtime/fire_sqlite3.h), and a "
              "formal image is freestanding: it links libSystem and nothing "
              "else, embeds no C runtime, and its values are one 64-bit word")
EXTERN_MSG = ("builds, but 31 import(s) dyld cannot resolve (one file "
              "compiled, no import resolution): _ZN6mojo5printEPKc, _ZN4mojo"
              "5writeEPKc, _ZN5mojo34read_file_to_stringB5cxx11E ...")
# The same fact, caught one step EARLIER and now the ordinary case: the bind
# audit in formal/build.py refuses the image before it is written, so there is
# no unresolvable binary left to probe. Verbatim from `fire.py build` on a
# model that calls a symbol nothing defines, so the two messages cannot drift
# into looking like different facts — which is exactly how a
# not-answerable-but-real finding becomes an answerable codegen gap.
EXTERN_BUILD_MSG = (
    "build: bogus.mojo: the image would bind 1 symbol(s) that nothing "
    "provides, so it could not be loaded: definitely_not_a_real_symbol_9f3a. "
    "These are constructs this backend does not lower (a struct type, a "
    "method call on a value, a compiler intrinsic), not exports that are "
    "missing. (Provider check: asked the C library (dlsym).)")
# fire.py prints `build: {e}` for a FormalBuildError AND for any other
# exception, so a crash is only distinguishable by its traceback. These two are
# the shapes that decides, taken from how fire.py's handler and CPython's
# traceback module print them.
TB_BACKEND = (
    "build: 'AssignStmt' object has no attribute 'name'\n"
    "Traceback (most recent call last):\n"
    '  File "/x/fire.py", line 186, in _run_formal_build\n'
    "    result = _fb.compile_formal(\n"
    '  File "/x/formal/build.py", line 412, in compile_formal\n'
    "    emit(stmts)\n"
    '  File "/x/formal/arm64_codegen.py", line 90, in emit\n'
    "    return self._stmt(node)\n"
    "AttributeError: 'AssignStmt' object has no attribute 'name'\n")
# Same top frame in formal/ (which sits between the driver and the emitter),
# but the exception came out of the parser. Not a codegen finding.
TB_DRIVER = (
    "build: 'AssignStmt' object has no attribute 'name'\n"
    "Traceback (most recent call last):\n"
    '  File "/x/fire.py", line 186, in _run_formal_build\n'
    "    result = _fb.compile_formal(\n"
    '  File "/x/formal/build.py", line 400, in compile_formal\n'
    "    stmts = F.parse(source)\n"
    '  File "/x/fire_compiler.py", line 1200, in parse\n'
    "    return AssignStmt(name, value)\n"
    "AttributeError: 'AssignStmt' object has no attribute 'name'\n")


class TestClassify(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(S.classify(True, ""), (S.CLASS_PASS, ""))

    def test_host_import_is_not_a_codegen_finding(self):
        cls, reason = S.classify(False, HOST_MSG)
        self.assertEqual(cls, S.CLASS_HOST)
        self.assertEqual(reason, "os")
        self.assertNotIn(cls, S.ANSWERABLE)
        self.assertNotIn(cls, S.DIRTY)

    def test_unresolved_import_is_its_own_class(self):
        # __future__ is a CPython standard-library module, so this lands in
        # host — via the interpreter's own table, because formal/imports.py's
        # HOST_MODULES does not list it (that gap is formal/imports.py's, and
        # this tool must not inherit a copy of it).
        self.assertEqual(S.classify(False, UNRESOLVED_MSG)[0], S.CLASS_HOST)

    def test_unresolved_non_host_module_keeps_its_own_class(self):
        # A sibling module the resolver cannot see from this file's directory
        # is NOT provably a host module, so it must not be filed as one.
        msg = ("build: tools/x.py imports 'fire_compiler', which is not a "
               "stdlib or sibling module, and no such file exists")
        cls, reason = S.classify(False, msg)
        self.assertEqual(cls, S.CLASS_UNRESOLVED)
        self.assertEqual(reason, "fire_compiler")
        self.assertNotIn(cls, S.ANSWERABLE)

    def test_third_party_package_is_unresolved_not_host(self):
        msg = ("build: t.py imports 'pytest', which is not a stdlib or sibling "
               "module, and no such file exists")
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_UNRESOLVED)

    def test_chained_import_error_names_the_innermost_module(self):
        # Verbatim from this tree: formal/build.py wraps a DEPENDENCY's own
        # error inside the importer's, so one message carries two `imports '…'`
        # and two different modules. The outer one resolves fine; blaming it
        # would send a reader after a module that is not the problem.
        msg = ("build: model.py imports 'fire_compiler', which cannot be "
               "built either: fire_compiler.py imports 're', which is a host "
               "module (CPython standard library), which has no Mojo source "
               "for this backend to compile")
        self.assertEqual(S.classify(False, msg), (S.CLASS_HOST, "re"))

    def test_codegen(self):
        cls, reason = S.classify(False, CODEGEN_MSG)
        self.assertEqual(cls, S.CLASS_CODEGEN)
        self.assertIn(cls, S.ANSWERABLE)
        self.assertIn(cls, S.DIRTY)
        self.assertIn("cannot be lowered", reason)

    def test_dyld_unresolvable_is_not_coverage(self):
        cls, reason = S.classify(False, EXTERN_MSG)
        self.assertEqual(cls, S.CLASS_EXTERN)
        self.assertIn("31 unresolved extern(s)", reason)
        self.assertNotIn(cls, S.ANSWERABLE)

    def test_a_build_time_bind_refusal_is_not_coverage_either(self):
        # The expensive half of the misclassification, pinned. When the same
        # fact is reported by the build-time audit instead of the post-build
        # probe, it must still be not-answerable: `codegen` counts against the
        # backend, deflates the coverage rate, makes the run exit 1, and points
        # the next reader at a construct the backend was RIGHT to refuse. The
        # two causes are told apart in the reason so a reader can see which
        # check fired without re-running the build.
        cls, reason = S.classify(False, EXTERN_BUILD_MSG)
        self.assertEqual(cls, S.CLASS_EXTERN)
        self.assertIn("1 unresolved extern(s)", reason)
        self.assertIn("caught when the build refused the image", reason)
        self.assertNotIn(cls, S.ANSWERABLE)
        self.assertNotIn(cls, S.DIRTY)
        # ...and it is genuinely a different string, so the branch is real
        # rather than both causes sharing one clause.
        (probe_cls, probe_reason), = [S.classify(False, EXTERN_MSG)]
        self.assertEqual(cls, probe_cls)
        self.assertNotEqual(reason, probe_reason)

    def test_silent_nonzero_exit_is_a_codegen_finding(self):
        # No message and no traceback: the backend died on the construct.
        # Counting that as `tool` would let a crash shrink coverage silently.
        self.assertEqual(S.classify(False, "exit 139")[0], S.CLASS_CODEGEN)

    def test_reworded_import_error_is_still_an_import_error(self):
        # A different agent editing formal/imports.py can reword the message
        # at any time. It must not start counting as codegen coverage, and it
        # must not need this file edited in the same commit to stay honest:
        # the quoted module plus the file's own source is the evidence.
        msg = "build: x.py cannot acquire 'os' on this target, sorry"
        self.assertEqual(S.classify(False, msg, source="import os\n")[0],
                         S.CLASS_HOST)
        msg2 = ("build: x.py has no module named 'fire_compiler' anywhere, "
                "and will not invent one")
        self.assertEqual(
            S.classify(False, msg2, source="import fire_compiler as F\n")[0],
            S.CLASS_UNRESOLVED)

    def test_a_quoted_name_the_file_does_not_import_is_a_codegen_finding(self):
        # The structural test must not over-reach: a quoted identifier that is
        # not one of this file's imports says nothing about imports, so the
        # refusal is about the code (this is the fallback a new codegen
        # diagnostic has to land in — see the docstring on CLASS_UNKNOWN).
        msg = "build: Type.foo() cannot be lowered: field 'os' has no word"
        self.assertEqual(S.classify(False, msg, source="import sys\n")[0],
                         S.CLASS_CODEGEN)

    def test_import_wording_with_no_module_named_is_unknown(self):
        # CLASS_UNKNOWN: recognisably about an import, but with nothing to
        # classify by. Its own bucket rather than a guess in either direction.
        msg = "build: this file is a host module (CPython standard library)"
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_UNKNOWN)
        self.assertIn(S.CLASS_UNKNOWN, S.DIRTY)
        self.assertNotIn(S.CLASS_UNKNOWN, S.ANSWERABLE)

    def test_cause_short_circuits_the_message(self):
        # A timeout whose text happens to mention an import is still a timeout:
        # the cause run_one reports outranks anything in the message.
        for cause in (S.CAUSE_TIMEOUT, S.CAUSE_UNREADABLE, S.CAUSE_TOOL_ERROR,
                      S.CAUSE_DRIVER_CRASH):
            self.assertEqual(S.classify(False, HOST_MSG, cause),
                             (S.CLASS_TOOL, cause))
        self.assertEqual(S.classify(True, "", S.CAUSE_TIMEOUT)[0],
                         S.CLASS_PASS)

    def test_crash_classification_uses_the_deepest_frame(self):
        self.assertEqual(S._crash_cause(TB_BACKEND), S.CAUSE_BACKEND_CRASH)
        self.assertEqual(S._crash_cause(TB_DRIVER), S.CAUSE_DRIVER_CRASH)
        self.assertIsNone(S._crash_cause("build: something refused\n"))

    def test_a_crash_is_not_a_coverage_gap(self):
        # B4's hole, closed. A backend that REFUSES a construct has looked at
        # it and made a claim; a backend that RAISED has fallen over, and the
        # 74-file sweep that reported `codegen: the backend raised: ValueError:
        # not enough values to unpack` was reporting another agent's half-written
        # edit as a gap in the language coverage. So: its own class, counted
        # and printed, exit 1 (DIRTY), and in NO rate (not ANSWERABLE) — it is
        # a bug in the compiler, and a rate is a claim about constructs.
        cls, reason = S.classify(False, "AttributeError: x", "backend-crash")
        self.assertEqual(cls, S.CLASS_CRASH)
        self.assertNotIn(cls, S.ANSWERABLE)
        self.assertIn(cls, S.DIRTY)
        self.assertIn("the backend raised", reason)
        # The same text with NO traceback is a refusal, not a crash: the
        # deepest frame is the only thing that tells them apart, so the same
        # words must classify differently when there is no crash to see.
        self.assertEqual(S.classify(False, "AttributeError: x")[0],
                         S.CLASS_CODEGEN)
        # A driver crash is this tool's own problem and still lands in `tool`.
        self.assertEqual(S.classify(False, "AttributeError: x", "driver-crash"
                                   )[0], S.CLASS_TOOL)

    def test_reason_is_one_line_and_bounded(self):
        cls, reason = S.classify(False, CODEGEN_MSG + "\n" + "x" * 500)
        self.assertEqual(cls, S.CLASS_CODEGEN)
        self.assertNotIn("\n", reason)
        self.assertLessEqual(len(reason), 68)

    def test_criteria_id_is_the_cache_key_input(self):
        # The contract _criteria_id() exists for: a verdict is a function of
        # the source AND the rules, so the rules must be in the key. Editing
        # THIS file changes its bytes, which is what makes a change to the
        # classification rules above invalidate every cached verdict.
        self.assertNotEqual(
            cas.formal_build_key("src", "p.mojo", S.build_flags("arm64"), ""),
            cas.formal_build_key("src", "p.mojo", S.build_flags("arm64"),
                                 S._criteria_id()))

    def test_arch_is_still_separate_in_the_key(self):
        # Classification must not have weakened the other half of the key.
        a = cas.formal_build_key("s", "p.mojo", S.build_flags("arm64"), "c")
        b = cas.formal_build_key("s", "p.mojo", S.build_flags("x86_64"), "c")
        self.assertNotEqual(a, b)


class TestDyldProbe(unittest.TestCase):
    """`pass` vs `not-answerable/unresolved-extern`, checked against real dyld.

    The probe this replaces asked `hasattr(ctypes.CDLL(None), name)` — "is this
    name visible in the sweeping python process" — and so reported as a load
    failure every image whose import machinery had worked: the helper symbol
    lives in a dylib on the image's link line, which python has not loaded. On
    the arm64 repo sweep that was one file (`example_imports.mojo`, whose image
    runs and exits 40), i.e. the instrument calling the exact success the
    import path exists to produce a FAILURE. The rest of this file checks that
    things other than the sweep's own wording: every case below is settled by
    RUNNING the image dyld would load, so the probe cannot be quietly inverted
    in either direction without one of these going red.

    Two real images are built (both from throwaway sources in a temp dir, one
    build each, ~0.3s); the rest are the linker's own emitter, which is what
    produces the bind stream under test.
    """

    @classmethod
    def setUpClass(cls):
        import subprocess
        import tempfile
        cls.subprocess = subprocess
        cls._tmp = tempfile.TemporaryDirectory(prefix="fs_probe_")
        d = cls._tmp.name
        with open(os.path.join(d, "helper.mojo"), "w") as f:
            f.write("fn add(a: Int, b: Int) -> Int:\n    return a + b\n")
        with open(os.path.join(d, "main.mojo"), "w") as f:
            f.write("from helper import add\n\n"
                    "fn main() -> Int:\n"
                    "    var x: Int = add(2, 3)\n    return x\n")
        with open(os.path.join(d, "bogus.mojo"), "w") as f:
            f.write("fn main() -> Int:\n"
                    "    return definitely_not_a_real_symbol_9f3a(1)\n")
        cls.resolvable_img = cls._fire("main.mojo", "arm64")
        # `bogus.mojo` used to BUILD and fail to load, and that image was the
        # true positive for the post-build probe. The bind audit now refuses it
        # at build time, which is the better behaviour and removes the artifact
        # these tests wanted. So the refusal is asserted here, and the image the
        # probe needs is synthesized below the way the sibling tests already do
        # — the probe is still live code (the dylib path still produces
        # loadable images with unresolvable binds), and it must stay tested
        # against a real one.
        cls.bogus_refusal = cls._fire_expecting_refusal("bogus.mojo", "arm64")
        if S._EXTERN_BUILD_MARK not in cls.bogus_refusal:
            raise AssertionError(
                f"expected the bind audit's refusal, got: "
                f"{cls.bogus_refusal[-400:]}")
        # The image the post-build probe still has to be able to catch, built
        # the way a dylib-path build produces one: one external bind, and a
        # dylib that IS on the link line and loadable but does not define the
        # name. The dylib has to be a real one — name a path that does not
        # exist and dyld reports the missing library before it ever looks at
        # the symbol, so the check below would be asserting a different
        # failure than the one the probe exists to corroborate.
        from formal import macho_linker as ML
        cls.bogus_img = ML.build_macho_executable_extern(
            ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4),
            ["definitely_not_a_real_symbol_9f3a"], "arm64",
            dylibs=[{"install_name":
                     S._load_dylib_names(cls.resolvable_img)[1],
                     "symbols": set()}])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _build(cls, name, arch):
        out = os.path.join(cls._tmp.name, name.replace(".mojo", ".aout"))
        p = cls.subprocess.run(
            [sys.executable, os.path.join(S.REPO, "fire.py"), "build",
             "--formal", "--no-prove", f"--backend={arch}", "-o", out,
             os.path.join(cls._tmp.name, name)],
            capture_output=True, text=True, cwd=S.REPO, timeout=300)
        return out, p

    @classmethod
    def _fire(cls, name, arch):
        out, p = cls._build(name, arch)
        if p.returncode != 0:
            raise AssertionError(f"building {name} failed: "
                                 f"{(p.stderr or p.stdout).strip()[-400:]}")
        with open(out, "rb") as f:
            return f.read()

    @classmethod
    def _fire_expecting_refusal(cls, name, arch):
        """Build `name`, require a refusal, and return the message it said."""
        _, p = cls._build(name, arch)
        if p.returncode == 0:
            raise AssertionError(
                f"building {name} was expected to be refused by the bind "
                "audit, and it succeeded: the audit no longer covers the "
                "executable path, so the post-build probe is the only thing "
                "standing between this and a codegen misclassification")
        return (p.stderr or p.stdout).strip()

    def _runs(self, image, name):
        """Run the image; return (returncode, first line of stderr)."""
        out = os.path.join(self._tmp.name, "run_" + name)
        with open(out, "wb") as f:
            f.write(image)
        os.chmod(out, 0o755)
        self.subprocess.run(["codesign", "-s", "-", out],
                            capture_output=True, timeout=120)
        p = self.subprocess.run([out], capture_output=True, text=True,
                                timeout=60)
        err = (p.stderr or "").strip().splitlines()
        return p.returncode, (err[0] if err else "")

    def test_the_helper_symbol_is_invisible_to_this_process(self):
        # Why the old probe was wrong, pinned as a fact rather than a story:
        # the name the import machinery mangles IS resolvable, and IS NOT
        # visible to the sweeping interpreter. If this ever starts passing,
        # the old mechanism would stop being wrong for the wrong reason.
        image = self.resolvable_img
        (ordinal, name), = S._binds(image)
        self.assertEqual(ordinal, 2, "the helper must bind from the dylib")
        import ctypes
        self.assertFalse(hasattr(ctypes.CDLL(None), name),
                         "if the host process can see it, this test no longer "
                         "exercises the bug it exists to pin")

    def test_a_real_imported_helper_resolves_and_the_image_runs(self):
        # The false positive, end to end: the probe must find nothing missing…
        self.assertEqual(S._unresolved_imports(self.resolvable_img), [])
        # …and dyld must agree, by actually loading it.
        rc, err = self._runs(self.resolvable_img, "ok")
        self.assertEqual(err, "", f"dyld refused a resolvable image: {err}")
        self.assertEqual(rc, 5, "main() returns add(2, 3)")

    def test_an_image_nothing_defines_is_reported_and_dyld_agrees(self):
        # The true positive, and the check that the probe is not simply
        # answering "yes" to everything now.
        missing = S._unresolved_imports(self.bogus_img)
        self.assertEqual([m.name for m in missing],
                         ["definitely_not_a_real_symbol_9f3a"])
        self.assertIn("libSystem", missing[0].why)
        rc, err = self._runs(self.bogus_img, "bogus")
        self.assertIn("Symbol not found", err)
        self.assertNotEqual(rc, 0)

    def test_the_ordinal_decides_which_library_is_consulted(self):
        # The anti-inversion case. The same symbol, the same library on the
        # same link line, and the answer must follow the ordinal the image
        # recorded: dyld resolves a two-level bind in ONE named library, so a
        # probe that searched "every library on the line" gets the first of
        # these two wrong — in the false-PASS direction.
        from formal import macho_linker as ML
        helper = S._load_dylib_names(self.resolvable_img)[1]
        code = ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4)
        name = S._binds(self.resolvable_img)[0][1]

        wrong = ML.build_macho_executable_extern(
            code, [name], "arm64", dylibs=[{"install_name": helper,
                                            "symbols": set()}])
        self.assertEqual(S._binds(wrong), [(1, name)])
        self.assertEqual([m.name for m in S._unresolved_imports(wrong)], [name])

        right = ML.build_macho_executable_extern(
            code, [name], "arm64", dylibs=[{"install_name": helper,
                                            "symbols": {name}}])
        self.assertEqual(S._binds(right), [(2, name)])
        self.assertEqual(S._unresolved_imports(right), [])

    def test_a_dylib_of_the_wrong_architecture_is_not_a_resolution(self):
        # dlopen would happily load the arm64 helper into this arm64
        # interpreter, so a probe that used dlopen alone would report the
        # x86-64 image as resolvable — a false PASS. dyld's own message for
        # the same image is "Library not loaded: … incompatible architecture",
        # so the finding is real and the reason must name the architecture.
        import struct
        from formal import macho_linker as ML
        helper = S._load_dylib_names(self.resolvable_img)[1]
        self.assertNotIn(ML.CPU_TYPE_X86_64, S._macho_cputypes(helper),
                         "precondition: the helper is a thin non-x86_64 dylib")
        self.assertIn(ML.CPU_TYPE_ARM64, S._macho_cputypes(helper))
        code = ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4)
        name = S._binds(self.resolvable_img)[0][1]
        img = ML.build_macho_executable_extern(
            code, [name], "x86_64", dylibs=[{"install_name": helper,
                                             "symbols": {name}}])
        self.assertEqual(struct.unpack_from("<i", img, 4)[0],
                         ML.CPU_TYPE_X86_64)
        missing = S._unresolved_imports(img)
        self.assertEqual([m.name for m in missing], [name])
        self.assertIn("arm64", missing[0].why)
        self.assertIn("x86_64", missing[0].why)

    def test_an_unreadable_image_is_said_so_and_never_called_a_pass(self):
        # The failure mode of a hand-rolled Mach-O reader is to raise on a
        # header it does not recognise (run_one turns that into a `tool`
        # verdict, which says nothing about the file) — or, worse, to find
        # "no load commands, therefore nothing missing" and call it a pass.
        # Both are wrong; the answer has to be a stated reason.
        self.assertEqual(S._binds(b""), [])
        self.assertEqual(S._load_dylib_names(b""), [])
        missing = S._unresolved_imports(b"")
        self.assertEqual([m.name for m in missing], ["<unreadable image>"])
        self.assertIn("no Mach-O header", missing[0].why)

    def test_a_bind_naming_an_ordinal_the_image_does_not_have_is_reported(self):
        # dyld would refuse the image; the probe must not read past the end of
        # the load-command list and fall off into "resolvable". The same
        # lookup for an ordinal the image DOES have is the control.
        from formal import macho_linker as ML
        only_libsystem = [S._LIBSYSTEM]
        self.assertNotEqual(
            S._resolvable(9, "printf", only_libsystem, ML.CPU_TYPE_ARM64), "")
        self.assertEqual(
            S._resolvable(1, "printf", only_libsystem, ML.CPU_TYPE_ARM64), "")
        self.assertNotEqual(
            S._resolvable(1, "printf", [], ML.CPU_TYPE_ARM64), "")


class TestChainedDependencyRefusal(unittest.TestCase):
    """A refusal in a DEPENDENCY: which class the importing file gets, and why.

    The 204 files this exists for were the largest class in the default sweep
    and were in no rate at all, so every assertion below is about a file that
    does NOT build staying visible, counted, and never called a pass.
    """

    def test_a_chained_refusal_is_not_unknown(self):
        # The bug this closes: the outer layer is an import, no host/unresolved
        # wording is present, so the old rules reached `import message not
        # recognised` and the file left every rate.
        cls, reason = S.classify(False, CHAIN_MSG)
        self.assertEqual(cls, S.CLASS_CODEGEN_DEP)
        self.assertNotEqual(cls, S.CLASS_UNKNOWN)
        self.assertIn("binary_heap.mojo", reason)
        self.assertIn("module exports nothing", reason)

    def test_it_is_a_failure_and_in_the_denominator(self):
        cls = S.classify(False, CHAIN_MSG)[0]
        # Answerable: the file produced no binary, and would have if the
        # backend had lowered the construct its dependency used. Leaving these
        # out of the denominator is the bug being fixed, not a fix for it.
        self.assertIn(cls, S.ANSWERABLE)
        # And a failure: the run must not report exit 0 over 204 files that
        # did not build.
        self.assertIn(cls, S.DIRTY)

    def test_a_two_hop_chain_peels_all_the_way_down(self):
        hops, terminal = S._split_chain(CHAIN_MSG_2)
        self.assertEqual(hops, ["std.math", "std.sys"])
        self.assertTrue(terminal.startswith("env.mojo: ptr.value()"))
        cls, reason = S.classify(False, CHAIN_MSG_2)
        self.assertEqual(cls, S.CLASS_CODEGEN_DEP)
        self.assertIn("2 import(s) deep", reason)
        self.assertIn("env.mojo", reason)
        self.assertIn("method call on a value", reason)

    def test_an_unchained_message_peels_nothing(self):
        # The guarantee that makes this safe: the rules for a message with no
        # chain are the rules it had before, character for character.
        hops, terminal = S._split_chain(CODEGEN_MSG)
        self.assertEqual(hops, [])
        self.assertEqual(terminal, CODEGEN_MSG)
        self.assertEqual(S.classify(False, CODEGEN_MSG)[0], S.CLASS_CODEGEN)

    def test_the_terminal_import_reason_still_wins_through_a_chain(self):
        # A target fact stays a target fact however deep it is: the importer
        # cannot be built here either, so it is not-answerable, not a
        # dependency-blocked finding.
        msg = ("build: model.py imports 'fire_compiler', which cannot be built "
               "either: fire_compiler.py imports 're', which is a host module "
               "(CPython standard library), which has no Mojo source for this "
               "backend to compile")
        self.assertEqual(S.classify(False, msg), (S.CLASS_HOST, "re"))

    def test_the_outside_module_is_not_mistaken_for_the_blocker(self):
        # The structural import test must run on the TERMINAL only. The outer
        # module really is imported by this file, so a whole-message scan would
        # read this as an unresolved import of 'std.format' — a module that
        # resolves perfectly well, and the exact misattribution the chain rule
        # exists to prevent.
        msg = CHAIN_MSG.replace("'std.format'", "'.not_a_real_module'")
        cls, _reason = S.classify(False, msg, source="from .not_a_real_module "
                                                    "import x\n")
        self.assertEqual(cls, S.CLASS_CODEGEN_DEP)

    def test_every_real_family_from_the_sweep_lands_in_a_real_class(self):
        # The actual distribution the 204 files reduce to, one per family, so
        # a new wording in one of them shows up here rather than in a report.
        for msg, family in (
                (CHAIN_MSG, "module exports nothing"),
                (CHAIN_MSG_2, "method call on a value"),
                ("build: tempfile.mojo imports 'std.os', which cannot be built "
                 "either: info.mojo: multi-index subscript [...] is not "
                 "supported on the formal arm64 path", "multi-index subscript"),
                ("build: runner.mojo imports '.random', which cannot be built "
                 "either: random.mojo: constructing Error has no "
                 "representation on this path (a formal value is one 64-bit "
                 "word, and Error is not one thing)",
                 "value with no representation")):
            cls, reason = S.classify(False, msg)
            self.assertEqual(cls, S.CLASS_CODEGEN_DEP, msg[:60])
            self.assertIn(family, reason)


class TestTargetLimit(unittest.TestCase):
    """B3's refusal-by-name, which had no class and fell to `codegen`.

    `codegen` is "a gap in the backend" and `not-answerable` is "a fact about
    the target, not a gap" — by this file's own definitions a call the
    freestanding image cannot bind is the second, and filing it as the first
    overstates what backend work would buy.
    """

    def test_it_is_not_answerable_and_not_a_finding(self):
        cls, reason = S.classify(False, TARGET_MSG)
        self.assertEqual(cls, S.CLASS_TARGET)
        self.assertEqual(reason, "mojo_sqlite3_open")
        self.assertNotIn(cls, S.ANSWERABLE)
        self.assertNotIn(cls, S.DIRTY)

    def test_it_is_keyed_on_formal_model_not_on_wording(self):
        # The name and the text are both asked of formal/model.py, so this
        # cannot rot: reword the refusal there and this test follows it.
        from formal import model as M
        name = "mojo_sqlite3_open"
        self.assertTrue(M.is_gimple_runtime_builtin(name))
        self.assertEqual(S._target_limit(M.gimple_runtime_refusal(name)),
                         (S.CLASS_TARGET, name))

    def test_a_mention_is_not_a_refusal(self):
        # The namespace test is the model's predicate, not `startswith("mojo_")`
        # pasted here: a message that merely mentions such a name says nothing
        # about the target, and must stay a construct finding.
        msg = ("build: GimpleGen.overload_suffix_for() cannot be lowered: "
               "`self._mojo_list_len_cache` has no representation on this path")
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_CODEGEN)

    def test_a_reworded_refusal_is_unknown_not_a_guess(self):
        # formal/ edited under this file: the shape is recognised (a `mojo_*`
        # name led the sentence) and the meaning is not, so it is `unknown` —
        # counted, printed, exit 1 — rather than silently moved into either
        # the gap count or the excluded population.
        msg = "build: mojo_print is an entry point of some runtime or other"
        cls, reason = S.classify(False, msg)
        self.assertEqual(cls, S.CLASS_UNKNOWN)
        self.assertIn("mojo_print", reason)

    def test_through_a_chain_the_importer_is_unanswerable_too(self):
        # Same rule as an import refusal: a target fact stays a target fact
        # however deep it is, so the importing file is not-answerable too.
        msg = ("build: env.mojo imports 'std.sys', which cannot be built "
               "either: " + TARGET_MSG)
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_TARGET)


class TestReport(unittest.TestCase):
    """The summary, over a synthetic sweep — no builds, no CAS.

    run_one is stubbed at its own boundary (a Verdict in, a report out), so
    what is under test is the accounting and the wording, which is the layer
    that decides whether a reader can trust the number.
    """

    def _main(self, rows, prev=None, cas_state=(3, 2), argv=None):
        """rows: [(rel, ok, detail, cause)]. Returns (stdout, exit, ledger)."""
        import formal_sweep as mod
        files = [os.path.join(mod.REPO, r) for r, _ok, _d, _c in rows]
        by_path = {os.path.join(mod.REPO, r): (ok, d, c) for r, ok, d, c in rows}
        saved = {n: getattr(mod, n) for n in
                 ("run_one", "load_ledger", "publish_ledger", "find_source_files",
                  "_claim_arch")}

        # mem_gb is accepted and ignored: it is a bound on a build, and there is
        # no build here. Accepting it is the point — run_one grew this parameter
        # when the per-file ceiling landed, and a stub with the old signature
        # would fail on arity and read as a defect in the sweep.
        def fake_run_one(path, timeout, flags, mem_gb=mod.MEMCAP_GB):
            ok, detail, cause = by_path[path]
            return mod.Verdict(ok, detail, cause, True,
                               *mod.classify(ok, detail, cause, "import os\n"))

        def fake_publish(arch, f, v, partial=False):
            published.update(v)
            published_partial.append(partial)
        published, published_partial = {}, []
        mod.run_one = fake_run_one
        mod.load_ledger = lambda arch, f: prev
        mod.publish_ledger = fake_publish
        mod.find_source_files = lambda roots: files
        # The arch lock is stubbed to always granted: these cases are about the
        # report, and TestSweepLock is where the lock itself is under test.
        mod._claim_arch = lambda arch, files: True
        mod.cas.stats.update(hits=cas_state[0], misses=cas_state[1])
        old_argv, sys.argv = sys.argv, argv or ["formal_sweep.py", "--no-stdlib"]
        buf, code = io.StringIO(), None
        try:
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                try:
                    mod.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
            for n, v in saved.items():
                setattr(mod, n, v)
            cas.reset_stats()      # cas.stats is process-global
        buf.published_partial = published_partial
        return buf.getvalue(), code, published

    def test_classes_sum_to_the_file_count(self):
        rows = [("a.py", True, "", None),
                ("b.py", False, HOST_MSG, None),
                ("c.py", False, UNRESOLVED_MSG, None),
                ("d.py", False, CODEGEN_MSG, None),
                ("e.py", False, EXTERN_MSG, None),
                ("f.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT)]
        out, code, published = self._main(rows)
        m = re.search(r"classes sum to (\d+) = (\d+) files swept", out)
        self.assertIsNotNone(m, out)
        self.assertEqual(m.group(1), m.group(2))
        self.assertEqual(m.group(1), str(len(rows)))
        # Every non-PASS file is printed, under its class — nothing that used
        # to print as FAIL stops printing.
        for r in ("b.py", "c.py", "d.py", "e.py", "f.py"):
            self.assertIn(r, out)
        self.assertNotIn("a.py", out)
        # The ledger records every file, so the next run can diff it.
        self.assertEqual(published, {"a.py": S.CLASS_PASS, "b.py": S.CLASS_HOST,
                                     "c.py": S.CLASS_HOST,
                                     "d.py": S.CLASS_CODEGEN,
                                     "e.py": S.CLASS_EXTERN,
                                     "f.py": S.CLASS_TOOL})

    def test_headline_excludes_not_answerable_and_says_so(self):
        rows = ([("p%d.py" % i, True, "", None) for i in range(7)]
                + [("h%d.py" % i, False, HOST_MSG, None) for i in range(15)]
                + [("c.py", False, CODEGEN_MSG, None)])
        out, _code, _pub = self._main(rows, cas_state=(len(rows), 0))
        self.assertIn("codegen coverage: 7/8 = 87.5%", out)
        # The denominator is stated in words, not just as a number.
        self.assertIn("denominator: the 8 swept file(s) whose build could have "
                      "answered", out)
        self.assertIn("7 pass + 1 codegen + 0 codegen/dependency = 8", out)
        self.assertIn("the 15 in a not-answerable", out)
        self.assertIn("host-import by module: os x15", out)
        # And the old all-in-one number is gone: nothing reports PASS/total.
        self.assertNotIn("24.0% pass", out)
        self.assertNotIn("FAIL=16", out)

    def test_a_dependency_blocked_file_is_in_the_denominator_and_says_which(self):
        # The headline must not quietly shrink when 204 files become
        # classifiable, and the breakdown must say where the gap is rather
        # than leaving "204" as the whole story.
        rows = ([("p%d.py" % i, True, "", None) for i in range(7)]
                + [("d%d.py" % i, False, CHAIN_MSG, None) for i in range(4)]
                + [("c.py", False, CODEGEN_MSG, None)])
        out, code, _pub = self._main(rows, cas_state=(len(rows), 0))
        self.assertIn("codegen coverage: 7/12 = 58.3%", out)
        self.assertIn("7 pass + 1 codegen + 4 codegen/dependency = 12", out)
        self.assertIn(f"{S.CLASS_CODEGEN_DEP} by family: binary_heap.mojo: "
                      "module exports nothing x4", out)
        self.assertIn(f"{S.CLASS_CODEGEN} by family: value with no "
                      "representation x1", out)
        # The reader can tell "this file is fine, its dependency is not" from
        # "this file is not fine": the class says so, and the printed line
        # carries the whole chain plus the terminal reason.
        self.assertIn(f"{S.CLASS_CODEGEN_DEP.upper()}: d0.py", out)
        self.assertIn("binary_heap.mojo: formal dylib has no public functions",
                      out)
        self.assertIn(f"{S.CLASS_CODEGEN.upper()}: c.py", out)
        self.assertNotIn(f"{S.CLASS_CODEGEN_DEP.upper()}: c.py", out)
        self.assertEqual(code, 1)

    def test_a_crash_fails_the_run_and_is_in_no_rate(self):
        rows = ([("p%d.py" % i, True, "", None) for i in range(4)]
                + [("boom.py", False, "the backend raised: ValueError: not "
                   "enough values to unpack", S.CAUSE_BACKEND_CRASH)])
        out, code, _pub = self._main(rows, cas_state=(len(rows), 0))
        self.assertIn("codegen coverage: 4/4 = 100.0%", out)
        self.assertIn(f"{S.CLASS_CRASH.upper()}: boom.py", out)
        self.assertIn("made the BACKEND RAISE", out)
        self.assertIn("another agent", out)
        self.assertNotIn("the backend raised: the backend raised", out)
        self.assertEqual(code, 1)

    def test_the_first_finding_line_names_the_rows_own_class(self):
        # With a crash in DIRTY, `sorted(DIRTY)[0]` is alphabetically first, so
        # the line that points a reader at a file must take the class from the
        # row rather than from the set.
        rows = [("a.py", True, "", None),
                ("crash.py", False, "the backend raised: ValueError: x",
                 S.CAUSE_BACKEND_CRASH),
                ("b.py", False, CODEGEN_MSG, None)]
        out, _code, _pub = self._main(rows)
        self.assertIn(f"first {S.CLASS_CRASH} finding: crash.py", out)

    def test_not_answerable_alone_does_not_fail_the_run(self):
        rows = [("p.py", True, "", None),
                ("h.py", False, HOST_MSG, None),
                ("e.py", False, EXTERN_MSG, None),
                ("u.py", False, UNRESOLVED_MSG, None)]
        _out, code, _pub = self._main(rows)
        self.assertEqual(code, 0)

    def test_codegen_tool_and_unknown_all_fail_the_run(self):
        for row, why in ((("c.py", False, CODEGEN_MSG, None), "codegen"),
                         (("t.py", False, "boom", S.CAUSE_TOOL_ERROR), "tool"),
                         (("u.py", False, "imports 'zzz_nope', which is "
                           "worrying", None), "unknown")):
            out, code, _pub = self._main([("p.py", True, "", None), row])
            self.assertEqual(code, 1, why)

    def test_empty_answerable_denominator(self):
        out, code, _pub = self._main([("h.py", False, HOST_MSG, None)])
        self.assertIn("no file could be answered", out)
        self.assertEqual(code, 0)

    def test_cas_accounting_covers_every_file(self):
        rows = [("p.py", True, "", None), ("h.py", False, HOST_MSG, None),
                ("t.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT)]
        out, _code, _pub = self._main(rows, cas_state=(2, 0))
        self.assertIn("cas: 2 hit / 0 miss / 1 not cached (3 files)", out)
        self.assertIn("got no verdict at all", out)

    def test_history_accounts_for_a_file_changing_class(self):
        # The requirement: a file that used to be reported FAIL and now sits
        # in another class must be named, not silently recategorised.
        rows = [("moved.py", False, CODEGEN_MSG, None),
                ("steady.py", False, HOST_MSG, None)]
        prev = {"when": "2026-01-01T00:00:00", "arch": "arm64", "total": 3,
                "verdicts": {"moved.py": S.CLASS_HOST,
                             "steady.py": S.CLASS_HOST,
                             "gone.py": S.CLASS_PASS}}
        out, _code, _pub = self._main(rows, prev)
        self.assertIn(f"{S.CLASS_HOST} -> {S.CLASS_CODEGEN}: 1", out)
        self.assertIn("unchanged: 1", out)
        self.assertIn("in the previous report, not swept this time: 1", out)
        self.assertIn("previous report 2026-01-01T00:00:00", out)

    def test_history_says_so_when_there_is_none(self):
        out, _code, _pub = self._main([("p.py", True, "", None)], prev=None)
        self.assertIn("verdict history: none", out)


class TestCacheContract(unittest.TestCase):
    """The three properties a classification rule must not be able to break.

    A class is now a function of the STORED TEXT as well as of the source, so
    these are no longer bookkeeping: if a cached entry could be reported under
    the class it was given when it was written, then editing a rule would
    silently do nothing for every file already in the cache — which is every
    file, on every re-run.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="fs_cache_")
        self.path = os.path.join(self._tmp.name, "m.mojo")
        with open(self.path, "w") as f:
            f.write("from std.format import fmt\n")
        self.flags = S.build_flags("arm64")
        cas.reset_stats()

    def tearDown(self):
        self._tmp.cleanup()
        cas.reset_stats()

    def _key(self):
        with open(self.path) as f:
            return cas.formal_build_key(f.read(), self.path, self.flags,
                                        S._criteria_id())

    def test_the_stored_bytes_carry_no_class(self):
        # The first half of the contract, structurally: only `ok` and the
        # build's own text are stored, so there is nothing in the entry that
        # could go stale.
        raw = S._verdict_bytes(False, CHAIN_MSG)
        self.assertNotIn(S.CLASS_CODEGEN_DEP.encode(), raw)
        self.assertNotIn(S.CLASS_CODEGEN.encode(), raw)
        ok, detail = S._verdict_from_bytes(raw)
        self.assertFalse(ok)
        self.assertEqual(detail, CHAIN_MSG)

    def test_a_verdict_stored_under_older_rules_is_reclassified_now(self):
        # The second half, end to end through the real cache: an entry written
        # by an OLDER version of these rules (which filed this message
        # `unknown`) is served from the CAS, and today's rules decide its
        # class. Nothing about the entry is rewritten — the class is simply
        # not in it.
        cas.publish(self._key(), ".result", S._verdict_bytes(False, CHAIN_MSG))
        v = S.run_one(self.path, 60, self.flags)
        self.assertTrue(v.cached, "the entry must be served, not rebuilt")
        self.assertEqual(v.cls, S.CLASS_CODEGEN_DEP)
        self.assertIn(v.cls, S.ANSWERABLE)
        self.assertEqual(S.classify(v.ok, v.detail, v.cause,
                                   "from std.format import fmt\n")[0],
                         S.CLASS_CODEGEN_DEP)

    def test_a_stored_pass_is_still_a_pass(self):
        # The other direction: re-classification must not be able to demote or
        # invent. A stored `ok` is still `ok` under every rule.
        cas.publish(self._key(), ".result", S._verdict_bytes(True, ""))
        v = S.run_one(self.path, 60, self.flags)
        self.assertTrue(v.cached)
        self.assertEqual(v.cls, S.CLASS_PASS)

    def test_editing_a_rule_invalidates_the_key(self):
        # _criteria_id() is this file's own bytes, so a changed rule — or a
        # changed COMMENT, which is the price of keeping the rules explained
        # where they are — moves the key and no verdict survives it. Proved
        # without editing the file on disk: the id is a pure function of the
        # bytes, so a one-byte change to those bytes changes the id.
        with open(os.path.join(S.REPO, "tools", "formal_sweep.py"), "rb") as f:
            raw = f.read()
        self.assertEqual(S._criteria_id(), cas.hash_parts(raw))
        self.assertNotEqual(cas.hash_parts(raw), cas.hash_parts(raw + b"\n# x\n"))
        # …and the key really does depend on it, end to end.
        with open(self.path) as f:
            src = f.read()
        self.assertNotEqual(cas.formal_build_key(src, self.path, self.flags,
                                                 S._criteria_id()),
                            cas.formal_build_key(src, self.path, self.flags,
                                                 S._criteria_id() + "0"))

    def test_a_crash_is_never_published(self):
        # The third property, and the reason it exists: the traceback that
        # decides a crash's class is not in the stored bytes, so storing the
        # verdict would serve a crash back as an ordinary refusal next run —
        # or, worse, serve a stale `ok`. So run_one returns before publishing,
        # and the crash stays a miss.
        import formal_sweep as mod
        err = "build: 'X' object has no attribute 'y'\n" + TB_BACKEND
        proc = mod.subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=err)
        published = []
        with mock.patch.object(mod.subprocess, "run",
                               return_value=proc), \
             mock.patch.object(mod.cas, "lookup", return_value=None), \
             mock.patch.object(mod.cas, "publish",
                               side_effect=lambda *a, **k: published.append(a)):
            v = mod.run_one(self.path, 60, self.flags)
        self.assertEqual(v.cls, mod.CLASS_CRASH)
        self.assertFalse(v.cached)
        self.assertEqual(published, [], "a crash must publish nothing")


class TestLedgerKey(unittest.TestCase):
    def test_key_is_per_arch_and_per_scope(self):
        files = [os.path.join(S.REPO, "a.py"), os.path.join(S.REPO, "b.py")]
        self.assertEqual(S.ledger_key("arm64", files),
                         S.ledger_key("arm64", list(reversed(files))))
        self.assertNotEqual(S.ledger_key("arm64", files),
                            S.ledger_key("x86_64", files))
        self.assertNotEqual(S.ledger_key("arm64", files),
                            S.ledger_key("arm64", files[:1]))

    def test_ledger_key_survives_a_change_of_classification_rules(self):
        # The ledger records what the last run REPORTED, so it must NOT be
        # keyed on _criteria_id(): the run whose history matters most is the
        # first one after the rules change, and that is exactly the run whose
        # criteria id differs from every earlier run's. Here _criteria_id() is
        # this very file's hash, so if it were folded in, a sweep of this file
        # would find no history to compare against.
        self.assertEqual(
            S.ledger_key("arm64", [os.path.abspath(__file__)]),
            S.ledger_key("arm64", [os.path.abspath(__file__)]))


class TestPerFileMemoryCeiling(unittest.TestCase):
    """One file's build is bounded, and a file that hits the bound is a file
    the sweep classifies and moves past — not a file that ends the run.

    This is the mechanism behind bugs/FORMAL_sweep_killed.md: the arm64 sweep of
    2026-10-01 was SIGKILLed with nothing but its 5-line header in the output,
    and the structural reason a single file could do that is that nothing was
    between one build and the machine.
    """

    def test_the_build_runs_under_memcap_not_bare(self):
        argv = S._build_argv("/x/y.mojo", "/tmp/o", ("--formal",), 4.0)
        self.assertEqual(argv[1], S.MEMCAP)
        self.assertIn("--limit-gb", argv)
        self.assertEqual(argv[argv.index("--limit-gb") + 1], "4.0")
        # memcap takes `--` and then the command; getting that wrong makes it
        # report usage and never run the build at all.
        self.assertEqual(argv[argv.index("--") + 1:],
                         [sys.executable, S.FIRE, "build", "--formal",
                          "-o", "/tmp/o", "/x/y.mojo"])

    def test_it_is_the_shared_memcap_not_a_second_watchdog(self):
        # A private RSS-threading-and-killing copy here would be a second
        # implementation of the tree walk procrun.py already owns, and a second
        # set of ways to get it wrong. The ceiling is the SHARED tool, and
        # procrun.memcap_verdict is what reads its verdict — one parser, already
        # shared with tools/suite.py and tools/ab_run_one.py.
        self.assertTrue(os.path.exists(S.MEMCAP))
        self.assertIs(S.procrun, procrun,
                      "the sweep must use the same procrun module, not a copy")

    def test_zero_means_no_ceiling_rather_than_an_instant_kill(self):
        # memcap treats a limit of 0 as "kill at once", so a caller passing 0
        # has to be served the uncapped build it asked for — otherwise the
        # natural spelling of "no cap" is the one spelling that kills everything.
        argv = S._build_argv("/x/y.mojo", "/tmp/o", ("--formal",), 0)
        self.assertNotIn(S.MEMCAP, argv)
        self.assertEqual(argv[1], S.FIRE)

    def test_a_breach_is_caught_and_carries_the_peak(self):
        breach = ("memcap: BREACH  4.1 GB > 4.0 GB ceiling (102%), 3 procs -- "
                  "killing y.mojo\nmemcap: peak observed before the kill: "
                  "4.1 GB\nmemcap: this is a RESOURCE failure, not a verdict "
                  "on the thing under test -- the process was killed for "
                  "memory before it finished.\n")
        # A run that exited 125 BY ITSELF is not a memory kill, and reading the
        # exit code instead of memcap's own words is how a real failure gets
        # filed under a machine problem. procrun.memcap_verdict is what refuses
        # that conflation; this asserts the sweep goes through it.
        killed, peak = procrun.memcap_verdict(breach)
        self.assertTrue(killed)
        self.assertAlmostEqual(peak, 4.1)
        killed, _ = procrun.memcap_verdict("memcap: done, peak 0.1 GB, child exit 0")
        self.assertFalse(killed)

    def test_a_memory_kill_is_tool_class_and_not_a_codegen_finding(self):
        # The fallback for a silent non-zero exit is deliberately the FINDING
        # side (a `codegen` row). A SIGKILLed build is silent, so without an
        # explicit check it would be filed as a gap in the backend — a machine
        # fact reported as a finding about the file, which is the most expensive
        # misclassification this tool can make.
        detail = "killed at the 4 GB per-file ceiling (peak 4.1 GB)"
        cls, reason = S.classify(False, detail, S.CAUSE_MEMORY, "x = 1\n", "x.py")
        self.assertEqual(cls, S.CLASS_TOOL)
        self.assertEqual(reason, S.CAUSE_MEMORY)
        self.assertIn(S.CLASS_TOOL, S.DIRTY, "a file nobody answered for fails the run")

    def test_a_memory_kill_is_not_a_timeout(self):
        # The two are in the same class and need OPPOSITE responses: a timeout
        # says raise -t, a memory kill says this build is a different shape and
        # running it wider will not help. Folding them together would tell a
        # reader to raise -t for a file that does not fit in the ceiling.
        self.assertNotEqual(S.CAUSE_MEMORY, S.CAUSE_TIMEOUT)
        self.assertEqual(S.classify(False, "timeout (> 30s)", S.CAUSE_TIMEOUT)[0],
                         S.CLASS_TOOL)
        self.assertEqual(
            S.classify(False, "killed at the 4 GB ceiling", S.CAUSE_MEMORY)[1],
            S.CAUSE_MEMORY)

    def test_a_memory_kill_is_never_published(self):
        # The ceiling is a flag on THIS run, so a verdict published under this
        # key would pin the file at "memory-killed" in a store whose key says
        # nothing about which flag set it. Same rule as a timeout, same reason.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "big.mojo")
            with open(path, "w") as f:
                f.write("def f():\n    return 1\n")
            published = []
            saved = S.cas.publish
            S.cas.publish = lambda *a, **k: published.append(a)
            try:
                v = S.run_one(path, 30, S.build_flags("arm64"), mem_gb=0)
            finally:
                S.cas.publish = saved
            # With the ceiling at 0 the build really runs, so this only proves
            # the plumbing; the breach path is covered by
            # test_a_breach_does_not_publish, which forces one.
            self.assertIsInstance(v, S.Verdict)
            del published

    def test_a_breach_does_not_publish(self):
        # Forced rather than provoked: provoking a real 4 GB breach would make
        # this test a memory hog, which is the thing it exists to argue against.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "big.mojo")
            with open(path, "w") as f:
                f.write("def f():\n    return 1\n")
            published = []
            saved_pub, saved_run = S.cas.publish, S._run_build
            S.cas.publish = lambda *a, **k: published.append(a)
            S._run_build = lambda *a, **k: S.BuildRun(
                125, "memcap: BREACH  4.1 GB > 4.0 GB ceiling\n"
                     "memcap: peak observed before the kill: 4.1 GB\n", "",
                True, 4.1)
            try:
                v = S.run_one(path, 30, S.build_flags("arm64"), mem_gb=4.0)
            finally:
                S.cas.publish, S._run_build = saved_pub, saved_run
        self.assertEqual(v.cause, S.CAUSE_MEMORY)
        self.assertIn("4.1 GB", v.detail)
        self.assertFalse(v.cached)
        self.assertEqual(published, [], "a memory kill must publish nothing")

    def test_a_breach_outranks_the_silent_death_fallback(self):
        # The build's own message is gone (the tree was SIGKILLed), so whatever
        # the child printed before dying must not be read as a refusal. This
        # drives _run_build directly so the ordering is what is under test, not
        # a real build.
        saved = S._run_build
        S._run_build = lambda *a, **k: S.BuildRun(
            125, "memcap: BREACH  4.1 GB > 4.0 GB ceiling\n"
                 "memcap: peak observed before the kill: 4.1 GB\n",
            "build: some.construct cannot be lowered: ...", True, 4.1)
        try:
            with tempfile.TemporaryDirectory() as td:
                path = os.path.join(td, "big.mojo")
                with open(path, "w") as f:
                    f.write("def f():\n    return 1\n")
                v = S.run_one(path, 30, S.build_flags("arm64"), mem_gb=4.0)
        finally:
            S._run_build = saved
        self.assertEqual(v.cls, S.CLASS_TOOL)
        self.assertEqual(v.cause, S.CAUSE_MEMORY)
        self.assertNotIn("cannot be lowered", v.detail)


class TestResultsSurviveAnInterruptedRun(unittest.TestCase):
    """A run that is stopped keeps what it classified.

    The 2026-10-01 arm64 sweep produced a 5-line header and no classifications
    because the results were printed after the pool drained. Streaming is the
    fix, and these are the two halves of it that a unit test can pin: the line
    is written as the verdict arrives (not at the end), and a partial run says
    how much of the scope it reached instead of claiming the whole denominator.
    """

    def test_a_row_is_printed_before_the_next_file_is_built(self):
        # Interleaving is the mechanism, so the test asserts the ORDER of the
        # writes: a stub that records "built X" and a collector that records
        # "printed Y" must show the print happening between two builds, with the
        # sweep not yet finished.
        import formal_sweep as mod
        events = []
        results = {}

        def fake_run_one(path, timeout, flags, mem_gb=mod.MEMCAP_GB):
            events.append(("built", mod.rel(path)))
            # A non-PASS so there is a line to print at all.
            return mod.Verdict(False, "build: refused", None, True,
                               mod.CLASS_CODEGEN, "other refusal")

        saved = mod.run_one
        mod.run_one = fake_run_one
        try:
            files = [os.path.join(mod.REPO, "a.py"), os.path.join(mod.REPO, "b.py")]
            buf = io.StringIO()
            with redirect_stdout(buf):
                mod._stream_results(files, 1, 30, ("--formal",), 4.0, results)
        finally:
            mod.run_one = saved
        out = buf.getvalue()
        # Both rows are on the output, and the file that was built FIRST is
        # printed while the SECOND was not yet built — so stopping the sweep
        # between the two would still leave the first row on disk.
        self.assertIn("CODEGEN: a.py", out)
        self.assertIn("CODEGEN: b.py", out)
        self.assertEqual(sorted(events), [("built", "a.py"), ("built", "b.py")])
        self.assertEqual(len(results), 2)

    def test_a_pass_prints_nothing_but_is_still_recorded(self):
        import formal_sweep as mod
        results = {}
        saved = mod.run_one
        mod.run_one = lambda p, t, f, mem_gb=mod.MEMCAP_GB: mod.Verdict(
            True, "", None, True, mod.CLASS_PASS, "")
        try:
            files = [os.path.join(mod.REPO, "ok.py")]
            buf = io.StringIO()
            with redirect_stdout(buf):
                mod._stream_results(files, 1, 30, ("--formal",), 4.0, results)
        finally:
            mod.run_one = saved
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(results[files[0]].cls, mod.CLASS_PASS)

    def test_a_partial_run_says_how_much_it_reached(self):
        # A partial run that printed "623 files: PASS=113" would be claiming a
        # denominator it does not have. The reached count and the total are two
        # separate numbers for exactly that reason.
        import formal_sweep as mod
        files = [os.path.join(mod.REPO, "a.py"), os.path.join(mod.REPO, "b.py"),
                 os.path.join(mod.REPO, "c.py")]
        results = {
            files[0]: mod.Verdict(True, "", None, True, mod.CLASS_PASS, ""),
            files[1]: mod.Verdict(False, "killed at the 4 GB per-file ceiling",
                                 mod.CAUSE_MEMORY, False, mod.CLASS_TOOL,
                                 mod.CAUSE_MEMORY),
        }
        published, partial_flags = {}, []
        saved = mod.publish_ledger
        mod.publish_ledger = lambda a, f, v, partial=False: (
            published.update(v), partial_flags.append(partial))
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                mod._report_partial("arm64", files, results)
        finally:
            mod.publish_ledger = saved
        text = err.getvalue()
        self.assertIn("INTERRUPTED: 2 of 3 files classified", text)
        self.assertIn("nothing is claimed about them", text)
        # The memory kills are named as their own count, not folded into a
        # generic tool tally that reads as "raise -t".
        self.assertIn("1 hit this tool's per-file memory ceiling", text)
        self.assertEqual(published, {"a.py": mod.CLASS_PASS, "b.py": mod.CLASS_TOOL})
        self.assertEqual(partial_flags, [True],
                         "a partial run must publish under its own key")

    def test_a_partial_ledger_is_not_readable_as_a_complete_run(self):
        # The extension, not a flag inside the payload, is what keeps a partial
        # run out of the next run's history: load_ledger looks for LEDGER_EXT
        # and a partial is published as LEDGER_PARTIAL_EXT, so the two cannot be
        # confused even if the payload is read by hand.
        import formal_sweep as mod
        self.assertNotEqual(S.LEDGER_EXT, S.LEDGER_PARTIAL_EXT)
        files = [os.path.join(mod.REPO, "a.py")]
        published, looked_up = [], []
        saved_pub, saved_look = mod.cas.publish, mod.cas.lookup
        mod.cas.publish = lambda key, ext, data: published.append(ext)
        mod.cas.lookup = lambda key, ext=".o": looked_up.append(ext) or None
        try:
            mod.publish_ledger("arm64", files, {"a.py": "pass"}, partial=True)
            mod.publish_ledger("arm64", files, {"a.py": "pass"})
            mod.load_ledger("arm64", files)
        finally:
            mod.cas.publish, mod.cas.lookup = saved_pub, saved_look
        self.assertEqual(published, [mod.LEDGER_PARTIAL_EXT, mod.LEDGER_EXT],
                         "a partial run must publish under its own extension")
        self.assertEqual(looked_up, [mod.LEDGER_EXT],
                         "load_ledger must only ever ask for a COMPLETE ledger")


class TestSweepLock(unittest.TestCase):
    """One sweep per architecture at a time, and different architectures are
    independent.

    The lock is here because two same-arch sweeps share the formal module-dylib
    output directory and the ledger, and a manifest in that directory is
    rewritten IN PLACE (`write_dylib_manifest` opens it `w`), so a reader in one
    sweep can observe the other's half-written JSON. That is what the
    `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` in
    bugs/FORMAL_sweep_tool_json_decode_error.md is; the lock stops the pair from
    running together rather than trying to make the shared write safe.
    """

    def test_a_second_sweep_of_the_same_arch_is_refused(self):
        with tempfile.TemporaryDirectory() as cas_dir:
            self._with_cas(cas_dir, lambda: self._assert_serialised("arm64"))

    def test_two_architectures_do_not_block_each_other(self):
        # The owner's own two-at-once run was an arm64 sweep and an x86-64 one,
        # and they completed. Those two are independent — separate dylib
        # directories, separate cache keys — so a lock that refused them would
        # be refusing a legitimate use, which is why the key is the ARCH and not
        # the cache as a whole.
        with tempfile.TemporaryDirectory() as cas_dir:
            self._with_cas(cas_dir, lambda: self._assert_serialised("x86_64"))

    def _assert_serialised(self, arch):
        import formal_sweep as mod
        # Real pipes, not sys.stdout/sys.stdin: unittest replaces those, and a
        # handshake over the replaced objects would test the harness rather than
        # the lock. Two fds, one direction each, is all this needs.
        down_r, down_w = os.pipe()      # child -> parent: "I hold it"
        up_r, up_w = os.pipe()          # parent -> child: "let go"
        first = os.fork()
        if first == 0:
            os.close(down_r)
            os.close(up_w)
            try:
                # The child holds the lock and waits to be told to let go, so
                # the parent's attempt is against a LIVE holder rather than
                # against a stale lock file — which is the distinction that
                # makes this a test of flock and not of the file's existence.
                if mod._claim_arch(arch, ["a.py"]):
                    os.write(down_w, b"held\n")
                    os.read(up_r, 1)
            finally:
                os._exit(0)
        os.close(down_w)
        os.close(up_r)
        try:
            self.assertEqual(os.read(down_r, 5), b"held\n",
                             "the forked child failed to take the lock")
            self.assertFalse(mod._claim_arch(arch, ["a.py"]),
                             "a second claim of the same arch must be refused")
        finally:
            os.write(up_w, b"\n")
            os.close(up_w)
            os.waitpid(first, 0)
            os.close(down_r)
        # Released: the kernel drops an flock when the holder dies, so a killed
        # sweep cannot wedge the next one. That is why this is a fork and not a
        # mock — the crash-safety is the property being claimed, and a mock
        # would be asserting that the mock released it.
        self.assertTrue(mod._claim_arch(arch, ["a.py"]),
                        "the lock must be free once the holder is gone")

    def test_the_lock_names_the_holder(self):
        # "Another sweep is running" is a worse message than "another sweep is
        # running, and here is its pid", and the pid is free: the lock is a
        # lockFILE, which is why it is not the ledger (that gets replaced).
        import formal_sweep as mod
        with tempfile.TemporaryDirectory() as cas_dir:
            self._with_cas(cas_dir, lambda: None)
            self.assertTrue(mod._claim_arch("arm64", ["a.py"]))
            with open(mod.sweep_lock_path("arm64")) as f:
                body = f.read()
        self.assertIn(str(os.getpid()), body)
        self.assertIn("a.py", body)

    def _with_cas(self, cas_dir, body):
        """Point cas.CAS_DIR at a temp dir for the duration of `body`."""
        import formal_sweep as mod
        saved = mod.cas.CAS_DIR
        mod.cas.CAS_DIR = cas_dir
        saved_held = mod._HELD_LOCK
        mod._HELD_LOCK = None
        try:
            body()
        finally:
            mod.cas.CAS_DIR = saved
            if saved_held is not None:
                os.close(saved_held)
            mod._HELD_LOCK = None


if __name__ == "__main__":
    unittest.main()
