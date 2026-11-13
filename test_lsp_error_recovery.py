#!/usr/bin/env python3
"""DIAGNOSTICS_lsp_error_recovery-part3: front-end error recovery reports an
unknown declaration and still retains/emits a following valid struct.

Regression for the `error_tolerance.mojo` shape: an unknown declaration at
module scope must be reported as a diagnostic ("use of unknown declaration")
while parsing/compilation continues so the subsequent struct is still present.
"""

import os
import tempfile

import fire_compiler as fc
from gimple_codegen import compile_to_gimple


UNKNOWN_DECL_SRC = "asdf\nstruct Good:\n    var x: Int\n"


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
    """Unknown declaration is reported, but the following struct is still emitted."""
    # Parser/front-end recovery path: recovered parse should record the diagnostic
    # and retain the subsequent struct declaration.
    tokens = fc.py_tokenize(UNKNOWN_DECL_SRC)
    p = fc.Parser(tokens)
    stmts = p.parse_module(recover=True)
    names = [getattr(s, "name", None) for s in stmts]
    assert "Good" in names, (
        f"expected struct Good to be retained after recovery, got {names!r} "
        f"stmts={[type(s).__name__ for s in stmts]}"
    )
    errors = [str(e) for e in getattr(p, "errors", [])]
    assert any("use of unknown declaration" in e for e in errors), (
        f"expected a 'use of unknown declaration' diagnostic, got errors={errors!r}"
    )

    # Full front-end/module emission must still produce/recognize the struct while
    # reporting the unknown-declaration diagnostic.
    try:
        out = _compile_full(UNKNOWN_DECL_SRC)
    except RuntimeError as e:
        msg = str(e)
        assert "use of unknown declaration" in msg, msg
        # The error path must not discard the recovered struct from module output
        # when the compiler produces partial/recovered output; if it raises before
        # emission, this assertion documents the contract for parts 1-2.
        raise
    else:
        assert "Good" in out, "expected struct Good to be emitted/recognized"


if __name__ == "__main__":
    test_lsp_error_recovery_reports_unknown_and_keeps_struct()
    print("ok")
