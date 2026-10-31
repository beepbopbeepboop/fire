"""Regression / pinning test for bug:CODEGEN_generator_function_Lib_enum.

The 4 @classmethod generators in Lib/enum.py (Flag/IntFlag
_iter_member_by_value_ / _iter_member_by_def_) must continue to be
honestly refused: `cls._flag_mask_` / `cls._value2member_map_` are
populated only via EnumMeta.__new__ dynamic metaclass machinery, not
literal class-body AssignStmts, so stubbing them would silently
miscompile (e.g. `_flag_mask_ = 0` makes every Flag iteration yield
nothing). A feature-sized dynamic-metaclass-attribute-modeling gap,
not a narrow codegen bug.
"""
import re
import gimple_codegen

ENUM_PY = '/Users/mrs/net/Python-3.14.6/Lib/enum.py'
REFUSAL_TEXT = (
    "a @classmethod generator that references `cls` in its body "
    "in an unsupported way is not supported"
)

NAMES = [
    "Flag", "_iter_member_by_value_",
    "Flag", "_iter_member_by_def_",
    "IntFlag", "_iter_member_by_value_",
    "IntFlag", "_iter_member_by_def_",
]


def test_enum_cls_refusal_is_honest():
    src = open(ENUM_PY).read()
    try:
        c, _ = gimple_codegen.compile_to_gimple_with_cpp(
            src, do_imports=False, filename=ENUM_PY)
        # Any successful compile (not refused) would be a regression:
        # a bad "fix" that stubs the dynamic attrs silently miscompiles.
        assert False, "compile succeeded unexpectedly (silent miscompile?)"
    except RuntimeError as e:
        msg = str(e)
        # The refusal messages must include the refusal text.
        assert REFUSAL_TEXT in msg, f"expected refusal text missing: {msg!r}"
    # Pinning test passes as long as refusal stays honest (not stubbing).
    print("PASS: refusal-pinned (feature-sized root cause unchanged)")


if __name__ == '__main__':
    test_enum_cls_refusal_is_honest()
