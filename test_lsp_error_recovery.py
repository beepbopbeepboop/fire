#!/usr/bin/env python3
"""DIAGNOSTICS_lsp_error_recovery-part3: front-end error recovery reports a
malformed declaration and still retains the following valid struct.

Regression for the `error_tolerance.mojo` shape: a malformed declaration at
module scope must be reported as a diagnostic while parsing CONTINUES, so the
subsequent struct is still parsed and present.

The source has to be a declaration that is genuinely malformed. A bare name
(`asdf`) is NOT one — the parser accepts it as an ordinary expression
statement, so `parse_module(recover=True)` records no error and the file
compiles silently. That was this test's original bug: its
"use of unknown declaration" assertion could never hold.

The "use of unknown declaration" wording belongs to a DIFFERENT layer — the
`@align(<unknown bare name>)` elaboration diagnostic in elaborate.py, pinned by
`test_lsp_error_recovery_part2.py`. This file pins the PARSER layer, which is
what the parent doc's symptom describes ("the parser must recover ... and keep
parsing, reporting the error and continuing to emit the following
declarations").
"""

import os
import tempfile

import fire_compiler as fc
from gimple_codegen import compile_to_gimple


# `def` with no name: the parser's recovery path drops the malformed
# declaration, records the diagnostic, and keeps going.
UNKNOWN_DECL_SRC = "def\nstruct Good:\n    var x: Int\n"

# The diagnostic the malformed declaration produces. Pinned verbatim so a
# wording change is a deliberate edit here, not a silent test drift.
PARSE_DIAGNOSTIC = "Expected NAME or KW"


def _compile_full(src, filename="t.mojo"):
    tmpdir = os.environ.get("TMPDIR", ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".mojo", dir=tmpdir, delete=False, mode="w"
    ) as f:
        f.write(src)
        fn = f.name
    try:
        return compile_to_gimple(src, do_imports=False, filename=fn)
    finally:
        try:
            os.unlink(fn)
        except OSError:
            pass


def test_lsp_error_recovery_reports_unknown_and_keeps_struct():
    """A malformed declaration is reported, and the following struct survives."""
    # The NON-recovering path raises: the diagnostic is real, not invented by
    # the recovering parse.
    try:
        fc.Parser(fc.py_tokenize(UNKNOWN_DECL_SRC)).parse_module()
    except SyntaxError as e:
        assert PARSE_DIAGNOSTIC in str(e), str(e)
    else:
        raise AssertionError(
            "expected the non-recovering parse to raise the declaration diagnostic"
        )

    # The recovering path records the SAME diagnostic and retains the
    # following struct — recovery continues rather than aborting the module.
    p = fc.Parser(fc.py_tokenize(UNKNOWN_DECL_SRC))
    stmts = p.parse_module(recover=True)
    names = [getattr(s, "name", None) for s in stmts]
    assert "Good" in names, (
        f"expected struct Good to be retained after recovery, got {names!r} "
        f"stmts={[type(s).__name__ for s in stmts]}"
    )
    assert [type(s).__name__ for s in stmts] == ["StructDef"], (
        "the malformed declaration should be dropped, not kept as a statement"
    )
    errors = [str(e) for e in getattr(p, "errors", [])]
    assert any(PARSE_DIAGNOSTIC in e for e in errors), (
        f"expected a '{PARSE_DIAGNOSTIC}' diagnostic recorded on the parser, "
        f"got errors={errors!r}"
    )

    # The front end still surfaces the diagnostic: recovery is a parser
    # behaviour, not a licence to compile a module the parser rejected.
    try:
        _compile_full(UNKNOWN_DECL_SRC)
    except SyntaxError as e:
        assert PARSE_DIAGNOSTIC in str(e), str(e)
    else:
        raise AssertionError(
            "expected compilation to fail with the declaration diagnostic"
        )


if __name__ == "__main__":
    test_lsp_error_recovery_reports_unknown_and_keeps_struct()
    print("ok")
