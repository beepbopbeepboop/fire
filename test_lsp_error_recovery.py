#!/usr/bin/env python3
"""DIAGNOSTICS_lsp_error_recovery-part3: front-end error recovery reports an
unknown declaration and still retains/emits a following valid struct.

Regression for the `error_tolerance.mojo` shape: an unknown declaration at
module scope must be reported as a diagnostic ("use of unknown declaration")
while compilation continues so the subsequent struct is still emitted.
"""

import os
import tempfile

from gimple_codegen import compile_to_gimple


# `@align(missing)` is a real unknown declaration: `missing` is neither a
# bracket parameter nor a module-level constant, so evaluating the decorator
# fails and the front end must report it instead of compiling the struct
# silently.  `Good` follows the failing declaration and must survive recovery.
UNKNOWN_DECL_SRC = """@align(missing)
struct Bad[T: Int]:
    var value: Int

struct Good:
    var y: Int

def main():
    var b = Bad[1]()
"""


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
    try:
        out = _compile_full(UNKNOWN_DECL_SRC)
    except RuntimeError as e:
        msg = str(e)
        assert "use of unknown declaration 'missing'" in msg, msg
        # The front end builds the module output before re-raising: the struct
        # declared after the failing declaration is still emitted.
        recovered = str(getattr(e, "module_output", ""))
        assert "typedef struct Good" in recovered, (
            "expected struct Good to be emitted after the recovered "
            f"unknown-declaration error; module output was {len(recovered)} "
            f"bytes: {recovered[:500]!r}"
        )
    else:
        raise AssertionError(
            "expected a 'use of unknown declaration' diagnostic for "
            f"'@align(missing)', but compilation succeeded and emitted "
            f"{len(out)} bytes"
        )


if __name__ == "__main__":
    test_lsp_error_recovery_reports_unknown_and_keeps_struct()
    print("ok")
