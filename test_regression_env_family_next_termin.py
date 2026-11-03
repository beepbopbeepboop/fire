#!/usr/bin/env python3
"""Pin the FORMAL_env_family_next_terminal regression: `env_round_trip`'s
`String(unsafe_from_utf8_ptr=ptr)` must not be refused when `ptr` is the
byte-pointer result of `external_call["getenv", _CPointer[UInt8, ...]]`.
Both halves of the fix must hold: the call-result value kind (POINTER_KIND,
not the int default) and the conversion-site exemption (pointer_intent)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import formal.model as M

def test_call_result_is_char_pointer_not_int():
    src = 'def f(s):\n    return external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]](s)\n'
    import formal.build as B
    import fire_compiler as F
    stmts = B.parse_module(src, "<pin>")
    for fn in B._extract_functions(stmts):
        for node in M.iter_nodes(fn.body):
            if isinstance(node, F.CallExpr) and M.is_external_call_template(node.func):
                kind = M.external_call_result_value_kind(node)
                assert kind is M.POINTER_KIND, f"expected POINTER_KIND, got {kind!r}"
                return
    raise AssertionError("no external_call node found")

def test_pointer_intent_exempts_string_conversion():
    from formal.model import string_conversion_refusal, STRING_POINTER_CONVERSION_KWARGS
    # The named-pointer keyword must make refusal return None (exempt)
    assert string_conversion_refusal("String", None, M.POINTER_KIND,
                                      pointer_intent=True) is None
    # Without pointer_intent, a non-text kind should refuse
    assert (string_conversion_refusal("String", None, M.INT_KIND,
                                      pointer_intent=False) is not None)

if __name__ == "__main__":
    test_call_result_is_char_pointer_not_int()
    test_pointer_intent_exempts_string_conversion()
    print("PASS regression_env_family_next_termin")
