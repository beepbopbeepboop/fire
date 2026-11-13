#!/usr/bin/env python3
"""DIAGNOSTICS_lsp_error_recovery-part1: parser recovers past a bad
declaration and retains a following valid struct.

Regression for parser-level recovery: a malformed/unknown declaration at
module scope must not abort parsing; the parser must synchronize and continue
so declarations that follow are still present in the module.
"""

import fire_compiler as fc


def parse_recover(src: str):
    tokens = fc.py_tokenize(src)
    p = fc.Parser(tokens)
    stmts = p.parse_module(recover=True)
    return stmts, p.errors


def test_recovers_past_malformed_decl_and_keeps_struct():
    # 'def' without a signature is a malformed declaration; parsing must not
    # abort and the subsequent struct must still be parsed.
    src = "def\nstruct Good:\n    var x: Int\n"
    stmts, errors = parse_recover(src)
    assert errors, "expected a recovered parse error for the malformed declaration"
    names = [getattr(s, "name", None) for s in stmts]
    assert "Good" in names, f"expected struct Good to be retained, got {names!r} and stmts={[type(s).__name__ for s in stmts]}"


def test_recovers_past_malformed_trait_and_keeps_struct():
    src = "trait\nstruct Good:\n    pass\n"
    stmts, errors = parse_recover(src)
    assert errors, "expected a recovered parse error"
    names = [getattr(s, "name", None) for s in stmts]
    assert "Good" in names, f"expected struct Good to be retained, got {names!r}"


if __name__ == "__main__":
    test_recovers_past_malformed_decl_and_keeps_struct()
    test_recovers_past_malformed_trait_and_keeps_struct()
    print("ok")
