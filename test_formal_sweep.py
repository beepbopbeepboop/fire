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
import signal
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tools"))

import cas
import formal_sweep as S
import formal_sweep_parity as P
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
        # A RELATIVE import, which is the shape whose symbols begin with an
        # underscore: `abi_module_name('._helper')` is `__helper`, so every
        # export of the imported module is `__helper_<name>_<hash>` and every
        # bind name the image records starts with `_`. The probe used to
        # `lstrip("_")` the name before handing it to dlsym, which turned
        # `__helper_twice_…` into `helper_twice_…` and reported a load failure
        # for an image that loads — measured on both `formal/hostmods/os`
        # hosts, both of which build, link and run. See
        # bugs/FORMAL_relative_submodule_abi_prefix_off_by_one.md.
        os.makedirs(os.path.join(d, "relpkg"), exist_ok=True)
        with open(os.path.join(d, "relpkg", "_helper.mojo"), "w") as f:
            f.write("fn twice(a: Int) -> Int:\n    return a + a\n")
        with open(os.path.join(d, "relpkg", "__init__.mojo"), "w") as f:
            f.write("from ._helper import twice\n\n"
                    "fn main() -> Int:\n"
                    "    var x: Int = twice(21)\n    return x\n")
        cls.relative_img = cls._fire("relpkg/__init__.mojo", "arm64")
        # A second relative-import fixture whose ABI prefix ITSELF begins with an
        # underscore, which is the shape the `lstrip("_")` normalisation cannot
        # survive. A relative import's prefix used to begin with one (`._helper`
        # inside no package was `__helper`), then stopped when a relative import
        # began carrying its parent's identity (`relpkg` above), and the fixture
        # that used to reproduce the defect quietly stopped doing so.
        #
        # The parent has to be a module whose own NAME begins with an underscore,
        # because that is the only place one survives: `abi_module_name` flattens
        # the dots (`a.b` -> `a_b`) and `macho_linker._bind_info` takes OFF the
        # single leading underscore of the C name when it writes the bind stream.
        # So a prefix of `_pkg__helper` exports `_pkg__helper_twice_…`, binds
        # `_pkg__helper_twice_…` (leading underscore), and `lstrip("_")` turns
        # that into `pkg__helper_twice_…`, which no library on the link line
        # exports — a load failure reported for an image that loads. A prefix of
        # `_helper` (an absolute `from _helper import`) is NOT enough: it binds
        # `helper_twice_…`, with no leading underscore, and the normalisation is
        # a no-op. Measured, both shapes, before this fixture was chosen.
        with open(os.path.join(d, "_helper.mojo"), "w") as f:
            f.write("fn twice(a: Int) -> Int:\n    return a + a\n")
        with open(os.path.join(d, "__pkg.mojo"), "w") as f:
            f.write("from ._helper import twice\n\n"
                    "fn main() -> Int:\n"
                    "    var x: Int = twice(21)\n    return x\n")
        # BOTH architectures, and the reason is not symmetry: the x86-64 half is
        # the one that goes through the export TRIE on this host (dlopen loads
        # only this process's own architecture), and `_macho_symbol` — the
        # function that replaced the `lstrip` — exists for that arm alone. An
        # end-to-end fixture for the normalisation defect that only ran natively
        # would leave the code that replaced it untested.
        cls.leading_underscore = {arch: cls._fire("__pkg.mojo", arch)
                                  for arch in ("arm64", "x86_64")}
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
        # A REAL x86-64 dylib with a real export trie, and an x86-64 image that
        # binds one of its names — the pair an arm64 host cannot dlopen. This is
        # the whole subject of the foreign-architecture cases below, and it is
        # built rather than faked because the answer now comes from reading the
        # trie: a file with a Mach-O header and no trie would be answered "I
        # cannot find out" again, and those tests would pass for the wrong
        # reason. `build_macho_dylib` needs the base address its own layout
        # implies, so the offset comes from the module rather than a constant —
        # and the entry is non-zero, because an export trie entry whose address
        # is 0 is not an export at all (see `_export_trie`) and the whole
        # fixture would be an empty library.
        from formal.macho_linker import TEXT_BASE
        cls.x_name = "helper_add_2dbb98"
        cls.x_dylib_path = os.path.join(d, "x86_helper.dylib")
        x_install = cls.x_dylib_path
        x_binary = ML.build_macho_dylib(
            b"", TEXT_BASE + ML.dylib_code_offset(x_install, False, [], False),
            [{"symbol": cls.x_name, "entry": TEXT_BASE + 16}], x_install,
            arch="x86_64")
        with open(cls.x_dylib_path, "wb") as f:
            f.write(x_binary)
        os.chmod(cls.x_dylib_path, 0o755)
        cls.x_img = ML.build_macho_executable_extern(
            ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4),
            [cls.x_name], "x86_64",
            dylibs=[{"install_name": x_install, "symbols": {cls.x_name}}])
        # And the same pair with a name the x86-64 dylib does NOT define, bound
        # FROM that dylib so the static arm is the one that has to catch it.
        cls.x_bogus_img = ML.build_macho_executable_extern(
            ML.build_macho_executable(b"\x1f\x20\x03\xd5" * 4),
            ["definitely_not_a_real_symbol_9f3a"], "x86_64",
            dylibs=[{"install_name": x_install,
                     "symbols": {"definitely_not_a_real_symbol_9f3a"}}])

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

    def test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs(self):
        # The `lstrip("_")` regression, end to end and settled by dyld.
        #
        # The precondition is stated as the INVARIANT rather than as the name
        # shape it used to have: a bind name is the C name and an export is that
        # name with dyld's one underscore in front, so the thing this test needs
        # is that the two are DIFFERENT strings — that is what makes
        # normalising one into the other wrong. Asserted rather than assumed,
        # because if the two ever coincided the test would pass for the wrong
        # reason and stop covering anything.
        #
        # It used to assert `name.startswith("_")`, which was true while a
        # relative import's ABI prefix began with one, and stopped being true
        # when a relative import began carrying its parent's identity —
        # `formal/build.py`'s `own_module_identity`, added because without it
        # the same file built as two different libraries depending on which
        # module reached it first. `._helper` inside `relpkg` is now the module
        # `relpkg._helper`, so the bind reads `relpkg__helper_twice_9f63a2` and
        # the export reads `_relpkg__helper_twice_9f63a2`. The image is
        # unaffected — it builds, the probe resolves it, and dyld runs it to 42
        # below, which is what this test is for. See
        # bugs/FORMAL_sweep_relative_import_bind_name_shape_moved.md for the
        # consequence: `lstrip("_")` is now a no-op on this fixture, so the
        # normalisation defect itself is pinned by the probe-level cases rather
        # than from here.
        names = [name for _ordinal, name in S._binds(self.relative_img)]
        self.assertTrue(names, "precondition: the image binds something")
        for name in names:
            self.assertNotEqual(name, "_" + name,
                                f"precondition: {name!r} is already the export "
                                f"name, so no normalisation could break it")
        self.assertEqual(S._unresolved_imports(self.relative_img), [])
        rc, err = self._runs(self.relative_img, "rel")
        self.assertEqual(err, "", f"dyld refused a resolvable image: {err}")
        self.assertEqual(rc, 42, "main() returns twice(21)")

    def test_a_bind_name_that_itself_begins_with_an_underscore_resolves(self):
        """The normalisation defect, end to end, on the shape that reproduces it.

        The case above can no longer make the original defect reproduce: its bind
        is `relpkg__helper_twice_…`, which begins with no underscore, so
        `lstrip("_")` is a no-op and any normalisation passes by accident. This
        fixture is the shape where the normalisation IS observable — the ABI
        prefix begins with an underscore — and it is what restores the end-to-end
        coverage the doc recorded as missing
        (`bugs/FORMAL_sweep_relative_import_bind_name_shape_moved.md`).

        Three things are asserted, in the order they matter:

        * **the precondition**: the bind name really does begin with an
          underscore, and the export really does begin with two. Without that
          this test would pass for the same reason the other one does — it would
          be exercising a normalisation that changes nothing;
        * **the normalisation is wrong here, and wrong in the direction that
          reports a failure**: the stripped name, mapped through `_macho_symbol`,
          is not what the library on the link line exports. That is the exact
          false answer the old probe gave — "this image needs a symbol nothing
          provides" — for an image that loads;
        * **the image resolves and runs**: on BOTH architectures. The x86-64 half
          goes through the export trie, which is the only place `_macho_symbol`
          is used, so an arm64-only fixture would leave the function that
          replaced the `lstrip` untested.
        """
        from formal import build as FB
        for arch, image in self.leading_underscore.items():
            names = [name for _ordinal, name in S._binds(image)]
            self.assertTrue(names, f"[{arch}] precondition: the image binds "
                                   f"something")
            dylibs = S._load_dylib_names(image)
            foreign = next((d for d in dylibs
                            if "libSystem" not in os.path.basename(d)), None)
            self.assertIsNotNone(foreign, f"[{arch}] no imported library on "
                                          f"the link line: {dylibs}")
            exports = set(FB.macho_dylib_exports(foreign))
            for name in names:
                self.assertTrue(
                    name.startswith("_"),
                    f"[{arch}] precondition: the bind {name!r} does not begin "
                    f"with an underscore, so lstrip('_') cannot change it and "
                    f"this fixture tests nothing (the shape to reach for is a "
                    f"relative import from a module whose own NAME begins with "
                    f"an underscore)")
                self.assertIn(S._macho_symbol(name), exports,
                              f"[{arch}] the image binds {name!r} and the "
                              f"library exports {sorted(exports)}")
                self.assertNotIn(
                    S._macho_symbol(name.lstrip("_")), exports,
                    f"[{arch}] the lstrip normalisation is expected to be "
                    f"wrong for {name!r} — if the two agree, the fixture has "
                    f"stopped reproducing the defect it exists for")
            self.assertEqual(S._unresolved_imports(image), [],
                             f"[{arch}] the probe must resolve every bind")
        rc, err = self._runs(self.leading_underscore["arm64"], "lead")
        self.assertEqual(err, "", f"dyld refused a resolvable image: {err}")
        self.assertEqual(rc, 42, "main() returns twice(21)")

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
        #
        # `_resolvable` returns (state, foreign, why) and only the triple
        # ("resolved", None, "") is success, so a caller cannot mistake a
        # partial answer — including "this host cannot find out" — for one.
        from formal import macho_linker as ML
        only_libsystem = [S._LIBSYSTEM]
        self.assertEqual(
            S._resolvable(9, "printf", only_libsystem, ML.CPU_TYPE_ARM64)[0],
            "unresolved")
        self.assertEqual(
            S._resolvable(1, "printf", only_libsystem, ML.CPU_TYPE_ARM64),
            ("resolved", None, ""))
        self.assertEqual(
            S._resolvable(1, "printf", [], ML.CPU_TYPE_ARM64)[0], "unresolved")

    def test_a_dylib_of_the_other_architecture_is_header_only_not_a_failure(self):
        # The 2026-10-01 false finding. An x86-64 image with correct x86-64
        # dylibs on its link line, probed from an arm64 process: dlopen cannot
        # load an x86-64 dylib into an arm64 process, and that failure says
        # NOTHING about whether the x86-64 image's own dyld could. Reporting it
        # as a load failure filed 7 correct images as unanswerable and made the
        # x86-64 sweep's pass count a floor rather than a number.
        from formal import macho_linker as ML
        self.assertEqual(S._host_cputype(), ML.CPU_TYPE_ARM64,
                         "this case is written for an arm64 host; the sweep "
                         "does run on x86-64 and the other direction is the "
                         "same code path with the roles swapped")
        state, foreign, why = S._loadable_for(self.x_dylib_path,
                                              ML.CPU_TYPE_X86_64)
        self.assertEqual(state, "header-only",
                         "an x86-64 dylib on an x86-64 image is not unloadable, "
                         "and this host's inability to dlopen it is no longer "
                         "the end of the answer")
        self.assertEqual(foreign, "x86_64")
        self.assertIn("cannot dlopen", why)

    def test_a_foreign_architecture_image_gets_a_verdict_from_an_arm64_host(self):
        # What the `header-only` state is FOR. Before 2026-10-02 this image was
        # `tool` with no verdict at all, on the grounds that an arm64 process
        # cannot dlopen its x86-64 helper — which is true and beside the point,
        # because dyld resolves the bind against that library's EXPORT TRIE, and
        # a trie is bytes in a file this process reads perfectly well.
        from formal import macho_linker as ML
        self.assertNotIn(ML.CPU_TYPE_ARM64,
                         S._macho_cputypes(self.x_dylib_path),
                         "precondition: the helper really is the other arch")
        (ordinal, name), = S._binds(self.x_img)
        self.assertEqual((ordinal, name), (2, self.x_name))
        self.assertEqual(S._unresolved_imports(self.x_img), [],
                         "a correct x86-64 image must not be reported broken, "
                         "and must not be left unanswered either")
        # And the finding still works through the same arm of the probe: a name
        # the x86-64 dylib does not export is reported, naming that library.
        missing = S._unresolved_imports(self.x_bogus_img)
        self.assertEqual([m.name for m in missing],
                         ["definitely_not_a_real_symbol_9f3a"])
        self.assertIn("x86_helper.dylib", missing[0].why)
        self.assertFalse(missing[0].unprovable)

    def test_the_two_arms_of_the_lookup_agree_on_a_library_both_can_read(self):
        # The safety net for the arm above, and it is the one that makes it safe
        # to use: for a library this host CAN dlopen, the export trie and dlsym
        # must return the same answer for every name. Measured over the CAS's own
        # arm64 dylibs, all 343 formal-module exports agree — and the first
        # version of the static arm did not. It looked the C name up where the
        # trie holds the Mach-O name, and called all three binds of
        # `formal/hostmods/ast.mojo` unexported by a dylib that exports them.
        from formal.build import macho_dylib_exports
        self.assertEqual(S._macho_symbol("helper_add"), "_helper_add",
                         "the mapping is the C name to the Mach-O name: exactly "
                         "one underscore, prepended and never stripped")
        path = S._load_dylib_names(self.resolvable_img)[1]
        exported = macho_dylib_exports(path)
        self.assertTrue(exported, "precondition: the helper exports something")
        for macho_name in exported:
            bind_name = macho_name[1:]     # exactly what the bind stream says
            self.assertEqual(S._exports(path, bind_name), ("exported", ""),
                             f"both arms disagree about {macho_name!r}")
        # The other direction, on a name neither library exports.
        self.assertEqual(S._exports(path, "definitely_not_a_real_symbol_9f3a"),
                         S._exports(path, "definitely_not_a_real_symbol_9f3a",
                                    static=True))

    def test_an_export_trie_that_cannot_be_read_is_still_unprovable(self):
        # `header-only` must not become a licence to pass. A file of the other
        # architecture whose trie this host cannot read leaves the name UNKNOWN
        # — no verdict, and no finding either — because both of those would be
        # inventions about the image derived from a reader that failed.
        from formal import macho_linker as ML
        fake = os.path.join(tempfile.gettempdir(), "sweep_no_trie_probe.dylib")
        with open(fake, "wb") as f:
            # A real Mach-O header claiming x86_64 and nothing else: enough for
            # _macho_cputypes, and no export trie for _static_exports to read.
            f.write(b"\xcf\xfa\xed\xfe" + b"\x07\x00\x00\x01" + b"\x00" * 24)
        try:
            state, foreign, _ = S._loadable_for(fake, ML.CPU_TYPE_X86_64)
            self.assertEqual(state, "header-only")
            self.assertEqual(foreign, "x86_64")
            found, why = S._exports(fake, "helper_add_2dbb98", static=True)
        finally:
            os.unlink(fake)
        self.assertEqual(found, "unprovable")
        self.assertIn("export table could not be read", why)

    def test_a_dylib_of_the_HOST_architecture_is_still_a_real_answer(self):
        # The conservative direction must not have been taken one step too far:
        # when the library IS this host's architecture, dlopen's verdict is a
        # fact about the image and is reported as a load failure if it fails.
        from formal import macho_linker as ML
        state, foreign, _ = S._loadable_for(S._LIBSYSTEM, ML.CPU_TYPE_X86_64)
        # libSystem is answered from the host, so it is loadable whatever the
        # image's arch — that is the documented exception, and it is the case
        # that must not be swept up in the new state.
        self.assertEqual((state, foreign), ("loadable", None))
        state, foreign, _ = S._loadable_for(S._load_dylib_names(
            self.resolvable_img)[1], ML.CPU_TYPE_ARM64)
        self.assertEqual((state, foreign), ("loadable", None),
                         "a real arm64 dylib on this host is loadable by "
                         "dlopen, so it is `loadable` and not `header-only` — "
                         "the two states must not have been merged")

    def test_a_file_whose_imports_are_all_unprovable_gets_no_verdict(self):
        # Not a finding, and not a pass: the class is `tool`, the cause is its
        # own, and nothing is cached. A `pass` would be inventing coverage the
        # probe never established; an `unresolved-extern` would be accusing a
        # correct image of a broken link line.
        #
        # What is left of this class since the export-trie arm landed: a library
        # this host cannot dlopen is now READ, so `unprovable` means the trie
        # could not be read (or the host's own architecture could not be
        # established) — a much narrower thing. The detail QUOTES that reason
        # rather than describing it, so this cannot keep asserting a sentence
        # about an arm64 host's inability to dlopen, which stopped being why
        # anything goes unprovable.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "x.mojo")
            with open(path, "w") as f:
                f.write("def f():\n    return 1\n")
            why = ("/tmp/x.dylib: its export table could not be read "
                   "(exports nothing, so a client could bind no name in it)")
            saved = S._unresolved_imports
            S._unresolved_imports = lambda binary: [
                S.Missing("helper_add", why, True, "x86_64")]
            try:
                v = S.run_one(path, 30, S.build_flags("x86_64"), mem_gb=0)
            finally:
                S._unresolved_imports = saved
        self.assertEqual(v.cls, S.CLASS_TOOL)
        self.assertEqual(v.cause, S.CAUSE_FOREIGN_ARCH)
        self.assertIn("helper_add", v.detail)
        self.assertIn("export table could not be read", v.detail)
        self.assertIn("Re-run on a x86_64 host", v.detail)
        self.assertFalse(v.cached)


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
        """rows: `[(rel, ok, detail, cause)]`, plus an OPTIONAL fifth element
        which is the path `classify` is given.

        Returns `(stdout, exit, ledger)`.  The fifth element exists because
        `built-with-admitted-contracts` is decided from a file's import closure and
        not from anything the build said: a harness that passes no path classifies
        every file as a plain `pass` and cannot exercise the class at all.
        """
        import formal_sweep as mod
        files = [os.path.join(mod.REPO, row[0]) for row in rows]
        by_path = {}
        for row in rows:
            by_path[os.path.join(mod.REPO, row[0])] = (row[1], row[2], row[3])
        saved = {n: getattr(mod, n) for n in
                 ("run_one", "load_ledger", "publish_ledger", "find_source_files",
                  "_claim_arch")}

        # mem_gb is accepted and ignored: it is a bound on a build, and there is
        # no build here. Accepting it is the point — run_one grew this parameter
        # when the per-file ceiling landed, and a stub with the old signature
        # would fail on arity and read as a defect in the sweep.
        # A row's optional FIFTH element is the path handed to `classify`.  It
        # has to exist at all, because `built-with-admitted-contracts` is decided
        # from the file's IMPORT CLOSURE and not from anything the build said —
        # so a harness that passes no path classifies every file as a plain
        # `pass` and cannot exercise the class at all.  The default keeps every
        # existing row's meaning.
        by_classify_path = {}
        for row in rows:
            if len(row) > 4 and row[4]:
                by_classify_path[os.path.join(mod.REPO, row[0])] = row[4]

        def fake_run_one(path, timeout, flags, mem_gb=mod.MEMCAP_GB):
            ok, detail, cause = by_path[path]
            return mod.Verdict(ok, detail, cause, True,
                               *mod.classify(ok, detail, cause, "import os\n",
                                             path=by_classify_path.get(path)))

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

    def test_a_file_that_builds_on_an_admitted_contract_is_its_own_class(self):
        """The trust boundary is a CLASS, and it is not a `pass`.

        Three things have to hold at once, and this is the assertion for all
        three because each one on its own is a way to lose the boundary quietly:
        the file is not reported as `pass`; it is not dropped out of the
        denominator either, because it DID build and the backend did answer its
        constructs; and the summary says so in a sentence rather than leaving a
        reader to work it out from a count.
        """
        admitted = self._admitted_file()
        clean = self._clean_file()
        cls, reason = S.classify(True, "", None, "", admitted)
        self.assertEqual(cls, S.CLASS_ADMITTED)
        self.assertIn("subprocess", reason)
        self.assertNotEqual(cls, S.CLASS_PASS)
        self.assertIn(S.CLASS_ADMITTED, S.ANSWERABLE,
                      "a file that BUILT belongs in the denominator")
        # …and a file with no admitted import is a plain pass, which is the
        # direction that matters: the class must not fire on a file that trusted
        # nothing.
        self.assertEqual(S.classify(True, "", None, "", clean)[0],
                         S.CLASS_PASS)
        out, code, ledger = self._main(
            [("admitted.py", True, "", None, admitted),
             ("clean.py", True, "", None, clean)])
        self.assertEqual(ledger["admitted.py"], S.CLASS_ADMITTED)
        self.assertEqual(ledger["clean.py"], S.CLASS_PASS)
        self.assertIn("1 pass + 1 built-with-admitted-contracts", out)
        self.assertIn("codegen coverage: 1/2", out)
        self.assertIn("NOT in the numerator", out)
        # An admitted file is printed like every other non-pass, and with its
        # REASON: its `detail` is the build's, which is empty for a successful
        # build, so printing only that prints a line with nothing in it.
        self.assertIn("BUILT-WITH-ADMITTED-CONTRACTS: admitted.py", out)
        self.assertIn("subprocess", out)
        # …and it does NOT make the run dirty: the backend did answer this
        # file's constructs, and a build that rests on a declared contract is not
        # a finding about the source.
        self.assertEqual(code, 0)

    def test_every_class_the_tool_can_produce_has_a_blurb(self):
        """A class with no blurb prints a bare count and no meaning.

        The rule `tools/suite.py` applies to the runner's statuses, applied here
        because this file has its own: `CLASS_ADMITTED` was added and the report
        is the tool's contract with a reader who has not read the tool.
        """
        missing = [c for c in S.CLASS_ORDER if c not in S.CLASS_BLURB]
        self.assertEqual(missing, [], f"classes with no blurb: {missing}")
        extra = [c for c in S.CLASS_BLURB if c not in S.CLASS_ORDER]
        self.assertEqual(extra, [], f"blurbs for classes never produced: {extra}")

    def _temp_source(self, text):
        """A temp source file, in the repo root so `resolve_module_path` can
        resolve its imports from it.

        The DIRECTORY is the point and the first version of this got it wrong: it
        passed `dir=HERE/.tmp` and `HERE` was not even bound in this module, so
        the helper raised `NameError` and the test errored instead of failing.
        The repo root is where `formal_sweep.REPO` is, which is where the sweep
        resolves a module from -- a temp file in `/tmp` would not find
        `formal/hostmods/` at all, and the class would not fire for a reason that
        has nothing to do with the class.
        """
        fd, path = tempfile.mkstemp(suffix=".mojo", dir=S.REPO)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _admitted_file(self):
        return self._temp_source("import subprocess\n\ndef main() -> int:\n"
                                 "    return subprocess.run(\"ls\")\n")

    def _clean_file(self):
        return self._temp_source("def main() -> int:\n    return 0\n")

    def test_headline_excludes_not_answerable_and_says_so(self):
        rows = ([("p%d.py" % i, True, "", None) for i in range(7)]
                + [("h%d.py" % i, False, HOST_MSG, None) for i in range(15)]
                + [("c.py", False, CODEGEN_MSG, None)])
        out, _code, _pub = self._main(rows, cas_state=(len(rows), 0))
        self.assertIn("codegen coverage: 7/8 = 87.5%", out)
        # The denominator is stated in words, not just as a number.
        self.assertIn("denominator: the 8 swept file(s) whose build could have "
                      "answered", out)
        # The admitted-contracts term is in the denominator and is the point of
        # this assertion: a file that builds on a DECLARED contract is neither a
        # pass nor out of scope, and the summary has to say so or the rate reads
        # as though admitting trust moved it.
        self.assertIn("7 pass + 0 built-with-admitted-contracts + 1 codegen"
                      " + 0 codegen/dependency = 8", out)
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
        self.assertIn("7 pass + 0 built-with-admitted-contracts + 1 codegen"
                      " + 4 codegen/dependency = 12", out)
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

    def test_the_tool_bucket_is_split_by_cause_with_its_share_of_the_scope(self):
        # `bugs/FORMAL_sweep_default_timeout_hides_a_crash_on_the_repos_own_files.md`:
        # one lumped "N files got no verdict (timeout/unreadable/memory-killed/
        # tool error) … a too-small -t is the usual cause" is what let a file
        # whose build CRASHES at 42 s read as a file that is merely slow, and the
        # crash never reached the ledger at all. So each cause is named, each
        # carries its share of the scope, and the timeout row says the answer is
        # unknown rather than absent.
        rows = [("p.py", True, "", None), ("h.py", False, HOST_MSG, None),
                ("t.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT),
                ("m.py", False, "killed at the 4.0 GB ceiling",
                 S.CAUSE_MEMORY),
                ("w.py", False, "memcap: big.mojo -- ceiling 4.0 GB across the "
                 "process tree", S.CAUSE_WRAPPER_DIED),
                ("u.py", False, "[Errno 2] No such file", S.CAUSE_UNREADABLE)]
        out, _code, _pub = self._main(rows)
        # Every cause in the bucket has its own line, and each says how much of
        # the classified scope it is — one file in six is 16.7%, which is the
        # fact that separates "one unknown file" from "most of this run is
        # unknown".
        flat = " ".join(out.split())
        self.assertIn("4 of the 6 classified file(s) (66.7%) got no verdict",
                      flat)
        for cause in (S.CAUSE_TIMEOUT, S.CAUSE_MEMORY, S.CAUSE_WRAPPER_DIED,
                      S.CAUSE_UNREADABLE):
            self.assertRegex(out, rf"{cause}\s+1 file\(s\) \(16\.7% of the "
                                 r"classified scope\)")
        # The timeout row says what the file's answer is: unknown at this -t.
        self.assertIn("unknown at this -t", out)
        # And it hands over the command that answers it, rather than leaving the
        # reader to reconstruct one. The paths are named while they are few, and
        # the -t it suggests is not the one that just failed.
        self.assertIn("re-answer them with a larger -t: python3 "
                      "tools/formal_sweep.py --arch arm64 -t 90 t.py", flat)
        self.assertNotIn("-t 30 t.py", flat)
        # The memory row must not read as "raise -t": it names the ceiling.
        self.assertIn("4 GB per-file ceiling", out)

    def test_a_tool_bucket_with_no_timeout_says_no_retry_command(self):
        # The command is for the one cause a reader can act on immediately;
        # printing it for a memory kill would tell a reader to wait longer for a
        # build that is too big.
        out, _code, _pub = self._main([
            ("p.py", True, "", None),
            ("m.py", False, "killed at the 4.0 GB ceiling", S.CAUSE_MEMORY)])
        self.assertNotIn("re-answer them", out)

    def test_many_timed_out_files_name_the_rows_rather_than_a_long_line(self):
        # Nine paths would be a 700-character summary line, and the paths are
        # already on the output as `timeout` rows — so past a handful the line
        # says where to find them instead of repeating them.
        rows = [("p.py", True, "", None)]
        rows += [(f"slow{i}.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT)
                 for i in range(9)]
        out, _code, _pub = self._main(rows)
        self.assertIn("the paths are the `timeout` rows above", out)
        self.assertNotIn("slow0.py slow1.py", out)

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
        # The key `run_one` will compute, argument for argument — including the
        # import-closure digest. A stored entry under a DIFFERENT key is not a
        # cached verdict, it is a miss with an entry beside it, and a test that
        # published one and asserted a hit would be asserting that the key
        # function ignores an input it takes.
        with open(self.path) as f:
            return cas.formal_build_key(f.read(), self.path, self.flags,
                                        S._criteria_id(),
                                        imports=S._imports_digest(self.path))

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
        proc = mod.BuildRun(1, "", err, False, None, False)
        published = []
        # `_run_build` itself, not `subprocess.run` under it: how the sweep
        # spawns a build (and kills its tree on a timeout) is the sweep's
        # business, and a mock of the spawning library underneath it silently
        # stops intercepting the moment that changes — which is how this test
        # came to be running a REAL build while believing it had stubbed one.
        with mock.patch.object(mod, "_run_build", return_value=proc), \
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

    The arm64 sweep of 2026-10-01 was SIGKILLed with nothing but its 5-line
    header in the output, and the structural reason a single file could do
    that is that nothing was between one build and the machine.
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
                True, 4.1, False)
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
            "build: some.construct cannot be lowered: ...", True, 4.1, False)
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


class TestWrapperDied(unittest.TestCase):
    """A build whose per-file wrapper never reported is not a finding.

    2026-10-02: six files per architecture in the b6 sweep carried memcap's
    BANNER as their `codegen` "refusal" — the class whose count is a gap in the
    backend, the class that fails a run — and were PUBLISHED to the CAS, so a
    machine fact outlived the run that observed it. The files are not memory
    hogs: `bit/mask.mojo`, one of the six, builds in 0.1 GB and is refused for a
    real reason. `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md`.
    """

    BANNER = ("memcap: big.mojo -- ceiling 4.0 GB across the process tree\n")

    def _run_with(self, buildrun, tag="x"):
        """run_one() against a forced _run_build, the way the breach tests do.

        Two things this has to get right or it tests nothing. `cas.publish` is
        stubbed, because a verdict reached through a forced _run_build is an
        artefact of the test and must not reach the store. And the source
        carries `tag`, because `cas.formal_build_key` takes the path only
        through the source it names — two tests with the same bytes share a key,
        so the second one gets the first one's CACHED verdict and never reaches
        the branch under test. (That is not hypothetical: the first draft of
        this class asserted on a detail and got the previous test's.)
        """
        saved_run, saved_pub = S._run_build, S.cas.publish
        S._run_build = lambda *a, **k: buildrun
        S.cas.publish = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as td:
                path = os.path.join(td, "big.mojo")
                with open(path, "w") as f:
                    f.write(f"# {tag}\ndef f():\n    return 1\n")
                return S.run_one(path, 30, S.build_flags("arm64"), mem_gb=4.0)
        finally:
            S._run_build, S.cas.publish = saved_run, saved_pub

    def test_a_wrapper_that_never_reported_is_no_verdict(self):
        v = self._run_with(S.BuildRun(-9, self.BANNER, "", False, None, True),
                          tag="no-verdict")
        self.assertEqual(v.cls, S.CLASS_TOOL)
        self.assertEqual(v.cause, S.CAUSE_WRAPPER_DIED)
        self.assertIn(S.CLASS_TOOL, S.DIRTY,
                      "a file nobody answered for fails the run")
        # NOT the memory wording, and that is the point of a separate label:
        # nothing was measured against the ceiling, so a reader told "killed at
        # the 4 GB ceiling" goes looking for a memory bug that is not there.
        self.assertNotIn("killed at", v.detail)
        self.assertNotIn("memcap:", v.detail)

    def test_a_wrapper_that_never_reported_is_not_published(self):
        # The same reason a timeout and a breach are not: the wrapper's death is
        # a fact about this run's machine, and a verdict published under this
        # key would pin the file here until the key changed.
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "big.mojo")
            # A distinct source for the reason _run_with's docstring gives: the
            # key takes the path only through the source, so a shared body would
            # let another test's verdict answer this one from the cache.
            with open(path, "w") as f:
                f.write("# not-published\ndef f():\n    return 1\n")
            published = []
            saved_pub, saved_run = S.cas.publish, S._run_build
            S.cas.publish = lambda *a, **k: published.append(a)
            S._run_build = lambda *a, **k: S.BuildRun(
                -9, self.BANNER, "", False, None, True)
            try:
                v = S.run_one(path, 30, S.build_flags("arm64"), mem_gb=4.0)
            finally:
                S.cas.publish, S._run_build = saved_pub, saved_run
        self.assertEqual(v.cause, S.CAUSE_WRAPPER_DIED)
        self.assertEqual(published, [],
                         "a machine fact must not become a cached verdict")

    def test_the_builds_own_message_still_wins(self):
        # The wrapper being silent is only a fact when the build said nothing
        # too. A build that refused a construct and then had its wrapper killed
        # has still refused it, and losing that would trade one misfiling for
        # another.
        v = self._run_with(S.BuildRun(
            -9, self.BANNER, "build: some.construct cannot be lowered: ...\n",
            False, None, True), tag="build-spoke")
        self.assertNotEqual(v.cause, S.CAUSE_WRAPPER_DIED)
        self.assertIn("cannot be lowered", v.detail)

    def test_a_wrapper_death_is_told_apart_from_a_breach_by_evidence(self):
        # memcap prints its banner before it starts anything and exactly one
        # outcome line afterwards, so "banner and no outcome" is the whole
        # discriminator. A breach, a clean finish and an interrupted watchdog
        # all report, and none of them is a wrapper death.
        self.assertTrue(procrun.memcap_wrapper_died(self.BANNER))
        self.assertFalse(procrun.memcap_wrapper_died(
            self.BANNER + "memcap: BREACH  4.1 GB > 4.0 GB ceiling\n"
            "memcap: peak observed before the kill: 4.1 GB\n"))
        self.assertFalse(procrun.memcap_wrapper_died(
            self.BANNER + "memcap: done, peak 0.1 GB across up to 1 procs "
            "(ceiling 4.0 GB), child exit 0\n"))
        self.assertFalse(procrun.memcap_wrapper_died(
            "build: some.construct cannot be lowered: ...\n"),
            "no memcap line at all means the ceiling was off (-M 0)")

    def test_the_row_names_the_signal_that_killed_the_wrapper(self):
        # "What killed the wrapper" was an OPEN QUESTION for this state — six
        # files per architecture in the 2026-10-02 sweep, and
        # bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md recorded the
        # candidates without concluding. The wrapper's own exit status answers
        # it, so the row says which signal rather than leaving a reader to
        # guess, and the SIGKILL case names the one thing in this repository
        # that sends one.
        v = self._run_with(S.BuildRun(-9, self.BANNER, "", False, None, True),
                           tag="sigkill")
        self.assertIn("killed by SIGKILL", v.detail)
        self.assertIn("tools/control.py guard", v.detail)
        # A SIGTERM could not produce this state at all — memcap handles it,
        # reports `interrupted` and kills its tree — so if one ever shows up
        # here it is a different story and the row must not claim the guard.
        v = self._run_with(S.BuildRun(-15, self.BANNER, "", False, None, True),
                           tag="sigterm")
        self.assertIn("killed by signal 15", v.detail)
        self.assertNotIn("control.py guard", v.detail)
        # And a wrapper that exited without a signal (a machine that reported
        # something else) says so rather than inventing a cause.
        v = self._run_with(S.BuildRun(1, self.BANNER, "", False, None, True),
                           tag="nosig")
        self.assertIn("exit status says nothing about how", v.detail)

    def test_memcap_handles_a_sigterm_so_it_cannot_produce_that_state(self):
        """The other half: remove the state rather than explain it.

        memcap installs a SIGTERM/SIGINT handler that takes the tree down and
        PRINTS the outcome, so a signalled wrapper is never the silent one. This
        runs the real binary rather than calling `main()`: what is under test is
        a signal delivered to a process with a child of its own, and the only
        faithful way to ask is to send one. Three properties, all of which the
        silent-death reader depends on:

          * it prints an outcome `procrun.memcap_accounted` recognises, so
            `memcap_wrapper_died` is False for the output a SIGTERM produces —
            the word is `interrupted`, which is the one in that set;
          * it exits 143 (128+15), so the caller can tell a terminated run from
            an interactive interrupt at 130;
          * the child is gone. A wrapper that dies on a TERM without killing
            its tree recreates the runaway the ceiling exists to prevent.
        """
        import signal as _signal
        import subprocess
        import time as _time
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "grandchild.pid")
            child = os.path.join(td, "slow.py")
            with open(child, "w") as f:
                f.write("import os, subprocess, sys, time\n"
                        "kid = subprocess.Popen([sys.executable, '-c', "
                        "'import time; time.sleep(600)'])\n"
                        f"open({marker!r}, 'w').write(str(kid.pid))\n"
                        "time.sleep(600)\n")
            proc = subprocess.Popen(
                [sys.executable, os.path.join(S.REPO, "tools", "memcap.py"),
                 "--limit-gb", "4", "--label", "sigterm", "--", sys.executable,
                 child],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                deadline = _time.time() + 20
                while _time.time() < deadline and not os.path.exists(marker):
                    _time.sleep(0.1)
                self.assertTrue(os.path.exists(marker),
                                "the workload under memcap never started")
                with open(marker) as f:
                    pid = int(f.read())
                proc.send_signal(_signal.SIGTERM)
                out, _ = proc.communicate(timeout=30)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 143,
                         f"a SIGTERMed wrapper exits 128+15; got "
                         f"{proc.returncode} with output {out!r}")
        self.assertIn("memcap: interrupted", out)
        self.assertTrue(procrun.memcap_accounted(out),
                        f"a signalled wrapper must report an outcome; "
                        f"got {out!r}")
        self.assertFalse(procrun.memcap_wrapper_died(out),
                         f"this output must not read as a silent wrapper "
                         f"death: {out!r}")
        # The child, gone. Polled rather than checked once, because it is
        # reparented to init when the workload dies and init takes a moment.
        alive = True
        deadline = _time.time() + 10
        while alive and _time.time() < deadline:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                alive = False
                break
            _time.sleep(0.2)
        self.assertFalse(alive,
                         f"the workload (pid {pid}) survived the wrapper's "
                         f"SIGTERM, which is the runaway the ceiling exists "
                         f"to prevent")

    def test_memcap_accounting_is_never_the_files_own_refusal(self):
        # as the last line of the captured text. The namedtuple's docstring
        # promises nothing downstream can match a `memcap:` line as if the build
        # had printed it; this is the line that promise is about. The CLASS is
        # left alone on purpose — the silent-death fallback is a documented
        # choice (a refusal whose message went to stdout is common), and this
        # test is about not putting the wrapper's bookkeeping in the file's
        # mouth, not about overruling that.
        v = self._run_with(S.BuildRun(
            -9, self.BANNER + "memcap: done, peak 0.2 GB across up to 1 procs "
            "(ceiling 4.0 GB), child exit -9\n", "", False, 0.2, False),
            tag="silent")
        self.assertNotIn("memcap:", v.detail)
        self.assertEqual(v.detail, "exit -9")


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
                mod._report_partial("arm64", files, results, 600, 4.0)
        finally:
            mod.publish_ledger = saved
        text = err.getvalue()
        self.assertIn("INTERRUPTED: 2 of 3 files classified", text)
        self.assertIn("nothing is claimed about them", text)
        # The memory kill is named as its own cause, with the ceiling this run
        # used, and NOT folded into a generic `tool` tally that reads as "raise
        # -t" — the two causes want opposite responses.
        self.assertIn("memory-killed", text)
        self.assertIn("4 GB per-file ceiling", text)
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


class TestAStoppedRunStopsBuilding(unittest.TestCase):
    """A sweep told to stop stops BUILDING, and keeps what was in flight.

    `bugs/FORMAL_sweep_sigterm_drains_the_whole_scope.md`. Every file is
    submitted to the pool up front, so the executor's queue is the whole run;
    returning from the reporting loop used to leave the `with` block, whose
    `__exit__` calls `shutdown(wait=True)` with `cancel_futures=False`, and each
    worker then pulled the next queued file until it reached the sentinel
    `shutdown` appends. Measured on the b6 sweep: thirteen children ten minutes
    after the signal, every one of them younger than it, and a second SIGTERM
    needed to end the run.

    The second half of the same bug is the numbers. `run_one` publishes to the
    CAS before it returns, so a build that ran during that shutdown left a
    verdict in the cache that the run's own ledger never mentioned — which is why
    the b6 work map reconstructs a run's classes from the CAS instead of reading
    its log. So the drain collects the `-j` builds that were already running.

    These are the mechanics, driven through the real executor and a real signal,
    because a test that patches the pool away cannot tell "cancelled the queue"
    from "never queued it". The signal is a genuine SIGINT sent from inside a
    build: that is what the handler is for, and it is the only way to exercise
    the path between "a build finished" and "the loop notices it should stop".
    """

    def _stopped_run(self, names, jobs=1, signal_from=None, hold=None):
        """Run `_stream_results` over `names`, SIGINTing it mid-run.

        `signal_from` names the file whose build raises the stop signal, once
        `hold` (the name of a second build) is running — so with `jobs=2` the
        run really is interrupted while a second build is in flight, which is the
        case the drain exists for. The signal is sent from a WORKER thread and
        handled in the MAIN thread, exactly as a SIGTERM from outside is.

        `hold`'s build blocks until the pool has been told to cancel its queue
        (`drained`), which is the event under test and also the only thing that
        can let that build finish: it stands in for a build that is a few
        seconds from a verdict, so it must be waited for rather than killed. A
        broken fix then fails the assertion instead of hanging the suite.

        Returns `(results, out, started, shutdowns)` where `shutdowns` is what
        the pool was asked to do, as `(wait, cancel_futures)` pairs.
        """
        import formal_sweep as mod
        import concurrent.futures as cf

        started, shutdowns = [], []
        running, drained = threading.Event(), threading.Event()

        class RecordingExecutor(cf.ThreadPoolExecutor):
            def shutdown(self, wait=True, *, cancel_futures=False):
                shutdowns.append((wait, cancel_futures))
                if cancel_futures:
                    drained.set()
                return super().shutdown(wait=wait, cancel_futures=cancel_futures)

        def fake_run_one(path, timeout, flags, mem_gb=mod.MEMCAP_GB):
            name = mod.rel(path)
            started.append(name)
            if name == hold:
                running.set()
                drained.wait(15)
            elif name == signal_from:
                if hold:
                    running.wait(15)
                os.kill(os.getpid(), signal.SIGINT)
                # The handler runs in the MAIN thread, which is at that moment
                # blocked waiting for a verdict, so give it the moment it needs
                # to notice — a real build does not finish in the same instant
                # the signal arrives, and this race is the one being pinned.
                time.sleep(0.2)
            return mod.Verdict(False, "build: refused", None, True,
                               mod.CLASS_CODEGEN, "other refusal")

        saved = mod.run_one
        mod.run_one = fake_run_one
        files = [os.path.join(mod.REPO, n) for n in names]
        results, buf = {}, io.StringIO()
        try:
            with mock.patch.object(mod.concurrent.futures,
                                   "ThreadPoolExecutor", RecordingExecutor):
                with redirect_stdout(buf):
                    interrupted = mod._stream_results(
                        files, jobs, 30, ("--formal",), 4.0, results)
        finally:
            mod.run_one = saved
        self.assertTrue(interrupted, "the run must report itself interrupted")
        return results, buf.getvalue(), started, shutdowns

    def test_the_files_that_never_started_are_not_built(self):
        # Three files, one worker, the signal raised by the first build while it
        # is still holding the worker. The old behaviour built all three: the
        # single worker pulled b and c in turn while `__exit__` waited.
        results, out, started, shutdowns = self._stopped_run(
            ["a.py", "b.py", "c.py"], jobs=1, signal_from="a.py")
        self.assertEqual(started, ["a.py"],
                         "a stopped sweep must not build the rest of its scope")
        self.assertEqual(sorted(results), [os.path.join(S.REPO, "a.py")])
        self.assertIn("CODEGEN: a.py", out)
        self.assertNotIn("b.py", out)
        self.assertIn((False, True), shutdowns,
                      "the queue must be cancelled, not walked")

    def test_the_builds_already_in_flight_are_kept_and_reported(self):
        # Two workers, so the signal arrives while a SECOND build is running.
        # That build publishes its verdict to the CAS before it returns, so
        # dropping it would leave the cache and the log disagreeing — the half of
        # the bug that made a run's numbers have to be reconstructed.
        results, out, started, shutdowns = self._stopped_run(
            ["a.py", "b.py", "c.py"], jobs=2, signal_from="a.py", hold="b.py")
        self.assertEqual(sorted(started), ["a.py", "b.py"],
                         "the queued third file must be the one that is dropped")
        self.assertEqual(sorted(os.path.basename(p) for p in results),
                         ["a.py", "b.py"])
        self.assertIn("CODEGEN: b.py", out,
                      "a build that finished during the drain must still print")
        self.assertIn((False, True), shutdowns)

    def test_an_unsignalled_run_classifies_every_file_and_is_not_a_drain(self):
        # The half that is NOT changed: nothing here is stopped, so no future is
        # cancelled, every file is classified, and the pool is shut down only by
        # its own `__exit__`.
        import formal_sweep as mod
        started = []
        saved = mod.run_one
        mod.run_one = lambda p, t, f, mem_gb=mod.MEMCAP_GB: (
            started.append(mod.rel(p)) or
            mod.Verdict(False, "build: refused", None, True,
                        mod.CLASS_CODEGEN, "other refusal"))
        files = [os.path.join(mod.REPO, n) for n in ("a.py", "b.py", "c.py")]
        results, buf = {}, io.StringIO()
        try:
            with redirect_stdout(buf):
                interrupted = mod._stream_results(
                    files, 2, 30, ("--formal",), 4.0, results)
        finally:
            mod.run_one = saved
        self.assertFalse(interrupted)
        self.assertEqual(sorted(started), ["a.py", "b.py", "c.py"])
        self.assertEqual(len(results), 3)
        for n in ("a.py", "b.py", "c.py"):
            self.assertIn(f"CODEGEN: {n}", buf.getvalue())


class TestSweepLock(unittest.TestCase):
    """One sweep per architecture at a time, and different architectures are
    independent.

    The lock is here because two same-arch sweeps share the formal module-dylib
    output directory and the ledger, and a manifest in that directory is
    rewritten IN PLACE (`write_dylib_manifest` opens it `w`), so a reader in one
    sweep can observe the other's half-written JSON — which is what the
    `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
    rows in the `tool` class are. The lock stops the pair from running
    together; the shared write itself is made safe separately, through
    `formal/build.py`'s `_write_json_atomic` (see
    `test_formal_manifest_atomic.py`), so this is belt to that braces.
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

class TestArmVsX86Parity(unittest.TestCase):
    """`tools/formal_sweep_parity.py`: two arms' logs, compared per FILE.

    The comparison was a hand-run scratch script in every map in this series, and
    the claim it supports — "the two architectures are the same sweep" — is the
    one that decides whether anyone spends a session on the x86-64 machine
    subset. So what is under test is the whole of the reporting layer: that a
    file missing from one arm's log is read as a PASS there (a pass prints
    nothing, so a plain diff of two logs cannot see the pass differences at
    all), that an architecture LABEL in a refusal is folded while an architecture
    name inside a FILE NAME is not, and that the differences the tool prints add
    up to the pass-count delta rather than being a list nobody has checked.

    No builds and no CAS: the unit under test reads two text files.
    """

    # Two messages the folding rule has to tell apart, both quoted from the
    # committed 2026-10-02 logs.
    ARM_LABEL = ("print() cannot tell whether SubscriptExpr is a string or a "
                 "number on the formal arm64 path, and guessing would print an "
                 "address as if it were text")
    X86_LABEL = ARM_LABEL.replace("arm64", "x86-64")
    # …which is what produced 10 on arm64 and 0 on x86-64 for one source) — a
    # refusal that names BOTH machines in one sentence, which is why the
    # reporting arm's own name cannot be all that gets folded.
    BOTH_MACHINES = ("This path has no MLIR, so it lowers a Mojo program to a "
                     "Mach-O image whose only value is a 64-bit word. Refused "
                     "rather than read out of a register, which is what produced "
                     "10 on arm64 and 0 on x86-64 for one source")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="fs_parity_")
        self.addCleanup(self._tmp.cleanup)

    def _log(self, arch, rows, files=4, passed=None):
        """Write one sweep log and return its path.

        `rows` is `[(rel, cls, detail)]`. The `PASS=` figure in the summary is
        derived from what is left over unless a test asks for another one, so a
        fixture cannot state a pass count that disagrees with its own rows —
        which is the arithmetic the tool checks.
        """
        passed = files - len(rows) if passed is None else passed
        body = ["memcap: parity -- ceiling 8.0 GB across the process tree",
                f"Sweeping {files} files through build --formal [{arch}] "
                f"(1 workers, 120s timeout, 4 GB per-file ceiling)..."]
        for rel, cls, detail in rows:
            body.append(f"{cls.upper()}: {rel}  ({detail})")
        body.append(f"[{arch}] {files} files: PASS={passed} "
                    f"not-pass={files - passed}")
        path = os.path.join(self._tmp.name, f"sweep-{arch}.txt")
        with open(path, "w") as f:
            f.write("\n".join(body) + "\n")
        return path

    def _compare(self, arm_rows, x86_rows, files=4):
        """`(changed, only_arm, only_x86, reasoned)` over two synthetic logs."""
        return P.compare(
            P.read_log(self._log("arm64", arm_rows, files))[1],
            P.read_log(self._log("x86_64", x86_rows, files))[1])

    def _printed(self, arm_rows, x86_rows, files=4):
        """What the tool prints for two synthetic logs."""
        out = io.StringIO()
        with redirect_stdout(out):
            P.report(self._log("arm64", arm_rows, files),
                     self._log("x86_64", x86_rows, files))
        return out.getvalue()

    # ── what a missing row means ──────────────────────────────────────────
    def test_a_file_only_one_arm_printed_a_row_is_a_pass_on_the_other(self):
        # The case a text diff cannot find, and the one the class counts point
        # at: in the committed logs `formal/hostmods/os/_syscalls.mojo` passes
        # on arm64 and is `not-answerable/unresolved-extern` on x86-64, which is
        # 126 pass against 125. A pass prints NO line, so the file is simply
        # absent from the ARM log — and "what is in log A but not log B" has
        # the opposite answer in each direction, which is why both are checked.
        changed, only_arm, only_x86, reasoned = self._compare(
            [], [("a.py", "codegen", "build: refused")], files=1)
        self.assertEqual(changed, [])
        self.assertEqual(reasoned, [])
        self.assertEqual(only_arm, [])
        self.assertEqual([p for p, _ in only_x86], ["a.py"])
        self.assertEqual(only_x86[0][1].cls, "codegen")
        changed, only_arm, only_x86, reasoned = self._compare(
            [("a.py", "codegen", "build: refused")], [], files=1)
        self.assertEqual((changed, reasoned, only_x86), ([], [], []))
        self.assertEqual([p for p, _ in only_arm], ["a.py"])

    def test_the_one_sided_rows_account_for_the_whole_pass_delta(self):
        # …in both directions, and as arithmetic the report prints. A
        # difference list that does not add up to the pass-count delta means a
        # row was lost or printed twice, so the list is not the whole story and
        # the report has to say so rather than look finished.
        self.assertIn("accounted for",
                      self._printed([("a.py", "codegen", "build: refused")],
                                    [], files=1))
        self.assertIn("accounted for", self._printed([], [], files=1))
        # A log whose summary claims a pass its own printed rows do not support:
        # 4 files with no rows is 4 passes, whatever the summary says, and every
        # file missing from a partial log looks exactly like a pass on the other
        # arm — the one class of difference this report must never invent.
        out = io.StringIO()
        with redirect_stdout(out):
            P.report(self._log("arm64", [], files=4, passed=1),
                     self._log("x86_64", [], files=4))
        self.assertIn("INCONSISTENT LOG", out.getvalue())
        self.assertIn("partial, or two runs in one file", out.getvalue())

    # ── class changes ─────────────────────────────────────────────────────
    def test_a_class_that_moved_is_named_in_both_directions(self):
        changed, only_arm, only_x86, reasoned = self._compare(
            [("a.py", "codegen", "build: refused here")],
            [("a.py", "not-answerable/host-import",
              "build: a.py imports 'os', which is a host module")])
        self.assertEqual([p for p, _, _ in changed], ["a.py"])
        self.assertEqual(changed[0][1].cls, "codegen")
        self.assertEqual(changed[0][2].cls, "not-answerable/host-import")
        self.assertEqual((only_arm, only_x86, reasoned), ([], [], []))

    # ── reasons, and the one normalisation ────────────────────────────────
    def test_an_architecture_aware_refusal_is_the_same_refusal_on_both_arms(self):
        # The measured instance: `test_llm/dumb_gemm.mojo` is `codegen` on both
        # arms for a print() it cannot classify, and the two messages name their
        # own architecture. Compared as text that is a REASON CHANGED row on
        # every sweep, forever, and it is a difference in the reader rather than
        # in the backend.
        _changed, _arm, _x86, reasoned = self._compare(
            [("dumb_gemm.mojo", "codegen", "build: " + self.ARM_LABEL)],
            [("dumb_gemm.mojo", "codegen", "build: " + self.X86_LABEL)])
        self.assertEqual(reasoned, [])

    def test_a_refusal_naming_both_machines_is_one_message(self):
        # From stdlib/sys/debug.mojo. Folding only the reporting arm's own name
        # leaves `0 on x86-64` facing `0 on <arch>`, which is a difference the
        # reader invents for itself.
        _changed, _arm, _x86, reasoned = self._compare(
            [("debug.mojo", "codegen", "build: " + self.BOTH_MACHINES)],
            [("debug.mojo", "codegen", "build: " + self.BOTH_MACHINES)])
        self.assertEqual(reasoned, [])

    def test_an_architecture_name_inside_a_file_name_is_not_a_label(self):
        # 12 of the 542 shared rows in the committed logs are messages that
        # name a FILE whose name contains an architecture —
        # `test_arm64_emission.py`, `formal/x86_64_codegen.py`, `jit/arm64.py`,
        # `test_formal_x86_64_parity.py`. Folding those renames the file the
        # row is filed under, and both arms fold their own copy of the same
        # string, so two identical rows come out different.
        for name in ("test_arm64_emission.py", "formal/x86_64_codegen.py",
                     "jit/arm64.py", "test_formal_x86_64_parity.py",
                     "tools/arm64_insn_audit.py"):
            with self.subTest(name=name):
                detail = f"build: {name} imports 'tempfile', which is a host module"
                self.assertEqual(P.fold_arch(detail), detail,
                                 f"{name} is a file name, not a machine label")
                _c, _a, _x, reasoned = self._compare(
                    [(name, "not-answerable/host-import", detail)],
                    [(name, "not-answerable/host-import", detail)])
                self.assertEqual(reasoned, [])

    def test_a_real_difference_of_reason_is_not_hidden_by_the_folding(self):
        # The other direction, and what keeps the normalisation from becoming a
        # way to stop seeing things: the same class and a genuinely different
        # refusal, which is what a `codegen` on both arms looks like when one
        # arm refused a subscript and the other a slice.
        _changed, _arm, _x86, reasoned = self._compare(
            [("a.py", "codegen", "build: a slice with a step is not lowered")],
            [("a.py", "codegen",
              "build: a subscript read of a String is not lowered")])
        self.assertEqual([p for p, _, _ in reasoned], ["a.py"])

    def test_the_refusing_module_is_compared_too(self):
        # Two dependency chains whose terminal message is the same sentence from
        # two different modules are two different gaps, and the class is
        # `codegen/dependency` on both — so the refuser is a third fact and not a
        # fourth reading of the reason.
        _changed, _arm, _x86, reasoned = self._compare(
            [("a.mojo", "codegen/dependency",
              "build: a.mojo imports 'b', which cannot be built either: "
              "tile.mojo: refused here")],
            [("a.mojo", "codegen/dependency",
              "build: a.mojo imports 'b', which cannot be built either: "
              "map.mojo: refused here")])
        self.assertEqual([p for p, _, _ in reasoned], ["a.mojo"])
        self.assertEqual(reasoned[0][1].refuser, "tile.mojo")
        self.assertEqual(reasoned[0][2].refuser, "map.mojo")

    # ── what is not comparable at all ─────────────────────────────────────
    def test_two_logs_of_one_architecture_are_refused(self):
        path = self._log("arm64", [])
        with self.assertRaises(SystemExit) as caught:
            P.report(path, path)
        self.assertIn("both logs are [arm64]", str(caught.exception))

    def test_a_file_that_is_not_a_sweep_log_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            junk = os.path.join(td, "not-a-sweep.txt")
            with open(junk, "w") as f:
                f.write("hello\n")
            with self.assertRaises(SystemExit) as caught:
                P.report(junk, self._log("x86_64", []))
        self.assertIn("NOT A SWEEP LOG", str(caught.exception))

    def test_two_sweeps_of_different_scopes_are_refused(self):
        # Every difference would then include the files only one of them swept,
        # which is a statement about the roots and not about either machine.
        with self.assertRaises(SystemExit) as caught:
            P.report(self._log("arm64", [], files=4),
                     self._log("x86_64", [], files=5))
        self.assertIn("not over the same scope", str(caught.exception))

    # ── and the two logs this repository actually has ─────────────────────
    def test_the_committed_arms_classify_every_shared_file_identically(self):
        # The claim in bugs/FORMAL_sweep_work_map_2026-10-02_b7.md §2.5, read
        # off the two committed logs rather than believed: 542 files classified
        # on both arms and NOT ONE of them with a different class. That is the
        # sentence which decided the x86-64 machine subset was not where the
        # remaining coverage was, so it is pinned against the logs themselves,
        # and a new divergence in either direction turns this red instead of
        # waiting to be noticed in a count.
        arm = os.path.join(S.REPO, "bugs/sweeps/sweep-arm-7.txt")
        x86 = os.path.join(S.REPO, "bugs/sweeps/sweep-x86-7.txt")
        for path in (arm, x86):
            if not os.path.exists(path):
                self.skipTest(f"{path} is not in this checkout")
        arm_arch, arm_rows, _ac, arm_files, _ap = P.read_log(arm)
        x86_arch, x86_rows, _xc, x86_files, _xp = P.read_log(x86)
        self.assertEqual((arm_arch, arm_files), ("arm64", 668))
        self.assertEqual((x86_arch, x86_files), ("x86_64", 668))
        changed, only_arm, only_x86, reasoned = P.compare(arm_rows, x86_rows)
        self.assertEqual([p for p, _, _ in changed], [],
                         "a file's CLASS differs between the two arms")
        self.assertEqual([p for p, _, _ in reasoned], [],
                         "a file is refused for a different reason on each arm")
        # What IS there, in those logs: one file passes on arm64 and is
        # `not-answerable/unresolved-extern` on x86-64. Asserted as a SHAPE and
        # not as a name, because a re-sweep against a probe that asks the right
        # question must be able to empty this list without a test edit; the
        # identity and its cause are in
        # bugs/FORMAL_sweep_x86_64_libsystem_probe_asks_the_host.md.
        self.assertEqual(only_arm, [])
        for path, row in only_x86:
            self.assertEqual(row.cls, "not-answerable/unresolved-extern")
            self.assertIn("dyld cannot resolve", row.reason)


if __name__ == "__main__":
    unittest.main()
