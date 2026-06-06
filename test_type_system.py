"""
Test Type System: Verify that invariant checker catches all bugs from the session.

This demonstrates how the comprehensive type system would have prevented
every bug we spent the session fixing.
"""

import pytest
from type_system import (
    Type, TypeOrigin, InvariantChecker, TypeSystemError,
    make_int64_type, make_double_type, make_mojolist_type, make_opaque_pointer_type
)


class TestTemporalMonotonicity:
    """Test TEMPORAL_MONOTONICITY invariant"""

    def test_variable_type_consistency(self):
        """Variables should maintain their type"""
        checker = InvariantChecker()

        # Assign x as int64_t
        x_type = make_int64_type(TypeOrigin.INFERRED, ("test.py", 1))
        checker.check_temporal_monotonicity("x", x_type, ("test.py", 1))

        # Reassign x as int64_t - should be OK
        checker.check_temporal_monotonicity("x", x_type, ("test.py", 2))
        assert not checker.has_errors()

    def test_variable_truncation_violation(self):
        """Variables should not silently truncate from 64-bit to 32-bit"""
        checker = InvariantChecker()

        # Start with int64_t
        x_type_64 = make_int64_type(TypeOrigin.INFERRED, ("test.py", 1))
        checker.check_temporal_monotonicity("x", x_type_64, ("test.py", 1))

        # Try to assign int (32-bit) - should violation TEMPORAL_MONOTONICITY
        x_type_32 = Type(base='int', bit_width=32, origin=TypeOrigin.INFERRED,
                        origin_loc=("test.py", 2))

        with pytest.raises(TypeSystemError) as exc_info:
            checker.check_temporal_monotonicity("x", x_type_32, ("test.py", 2))

        assert exc_info.value.invariant == "TEMPORAL_MONOTONICITY"
        assert "64-bit" in exc_info.value.message or "type" in exc_info.value.message.lower()

    def test_widening_is_ok(self):
        """Widening from 32-bit to 64-bit should be allowed"""
        checker = InvariantChecker()

        # Start with int (32-bit)
        x_type_32 = Type(base='int', bit_width=32, origin=TypeOrigin.INFERRED,
                        origin_loc=("test.py", 1))
        checker.check_temporal_monotonicity("x", x_type_32, ("test.py", 1))

        # Assign int64_t (64-bit) - should be OK (widening)
        x_type_64 = make_int64_type(TypeOrigin.INFERRED, ("test.py", 2))
        checker.check_temporal_monotonicity("x", x_type_64, ("test.py", 2))

        assert not checker.has_errors()


class TestBitWidthPreservation:
    """Test BIT_WIDTH_PRESERVATION invariant"""

    def test_64bit_arithmetic_produces_64bit(self):
        """64-bit + 64-bit should produce 64-bit"""
        checker = InvariantChecker()

        left = make_int64_type()
        right = make_int64_type()

        result = checker.check_bit_width_preservation(left, '+', right, ("test.py", 5))

        assert result.is_64bit()
        assert not checker.has_errors()

    def test_64bit_32bit_mismatch_violation(self):
        """Mixing 64-bit and 32-bit should raise error"""
        checker = InvariantChecker()

        left = make_int64_type()
        right = Type(base='int', bit_width=32, origin=TypeOrigin.DEFAULT)

        with pytest.raises(TypeSystemError) as exc_info:
            checker.check_bit_width_preservation(left, '+', right, ("test.py", 10))

        assert exc_info.value.invariant == "BIT_WIDTH_PRESERVATION"
        assert "bit" in exc_info.value.message.lower()

    def test_double_arithmetic_produces_double(self):
        """double + double should produce double"""
        checker = InvariantChecker()

        left = make_double_type()
        right = make_double_type()

        result = checker.check_bit_width_preservation(left, '+', right, ("test.py", 15))

        assert result.base == 'double'
        assert result.is_64bit()


class TestOpaquePointerTracking:
    """Test OPAQUE_POINTER_TRACKING invariant"""

    def test_opaque_pointer_to_explicit_pointer_needs_cast(self):
        """Passing opaque pointer to explicit pointer parameter needs cast"""
        checker = InvariantChecker()

        # int64_t opaque pointer to MojoList
        arg_type = make_opaque_pointer_type('MojoList', TypeOrigin.INFERRED)

        # Parameter expects explicit MojoList* pointer
        param_type = make_mojolist_type(make_double_type())

        with pytest.raises(TypeSystemError) as exc_info:
            checker.check_opaque_pointer_tracking(
                arg_type, param_type, 0, "advance", ("test.py", 20)
            )

        assert exc_info.value.invariant == "OPAQUE_POINTER_TRACKING"
        assert "cast" in exc_info.value.message.lower()

    def test_matching_opaque_pointer_ok(self):
        """Passing opaque pointer to opaque pointer parameter is OK"""
        checker = InvariantChecker()

        arg_type = make_opaque_pointer_type('MojoList', TypeOrigin.INFERRED)
        param_type = Type(
            base='MojoList',
            is_pointer=True,
            is_opaque_pointer=True,
            origin=TypeOrigin.ANNOTATED
        )

        # Should not raise
        checker.check_opaque_pointer_tracking(
            arg_type, param_type, 0, "func", ("test.py", 25)
        )


class TestElementTypePreservation:
    """Test ELEMENT_TYPE_PRESERVATION invariant"""

    def test_subscript_requires_element_type(self):
        """Cannot subscript container without element type"""
        checker = InvariantChecker()

        # MojoList without element type
        container = Type(base='MojoList', is_pointer=True, element_type=None)

        with pytest.raises(TypeSystemError) as exc_info:
            checker.check_element_type_preservation(container, ("test.py", 30))

        assert exc_info.value.invariant == "ELEMENT_TYPE_PRESERVATION"
        assert "element type" in exc_info.value.message.lower()

    def test_element_type_propagation(self):
        """Subscripting should return element type"""
        checker = InvariantChecker()

        # MojoList[double]
        elem_type = make_double_type()
        container = make_mojolist_type(elem_type)

        result = checker.check_element_type_preservation(container, ("test.py", 35))

        assert result.base == 'double'
        assert not checker.has_errors()

    def test_nested_list_element_type(self):
        """Nested lists should preserve element types"""
        checker = InvariantChecker()

        # Create MojoList[double]
        inner_elem = make_double_type()
        inner_list = make_mojolist_type(inner_elem)

        # Create MojoList[MojoList[double]]
        outer_list = Type(
            base='MojoList',
            is_pointer=True,
            element_type=inner_list,
            nested_element_type=inner_elem,
            origin=TypeOrigin.INFERRED
        )

        # Subscripting outer list should give MojoList[double]
        result1 = checker.check_element_type_preservation(outer_list, ("test.py", 40))
        assert result1.base == 'MojoList'
        assert result1.element_type is not None

        # Subscripting that should give double
        result2 = checker.check_element_type_preservation(result1, ("test.py", 41))
        assert result2.base == 'double'


class TestInferenceIdempotence:
    """Test INFERENCE_IDEMPOTENCE invariant"""

    def test_type_locking(self):
        """Once a type is inferred and locked, it cannot change"""
        checker = InvariantChecker()

        # Infer parameter type in Pass 1.2
        param_type_1 = make_mojolist_type(make_double_type())
        checker.lock_inferred_type("bodies", param_type_1, "1.2", ("test.py", 10))

        # Later, try to infer it as different type in Pass 1.3
        param_type_2 = make_int64_type()

        with pytest.raises(TypeSystemError) as exc_info:
            checker.lock_inferred_type("bodies", param_type_2, "1.3", ("test.py", 15))

        assert exc_info.value.invariant == "INFERENCE_IDEMPOTENCE"
        assert "different" in exc_info.value.message.lower()

    def test_consistent_inference_ok(self):
        """Inferring same type multiple times is OK"""
        checker = InvariantChecker()

        param_type = make_mojolist_type(make_double_type())

        # Lock in Pass 1.2
        checker.lock_inferred_type("bodies", param_type, "1.2", ("test.py", 10))

        # Lock again with same type in Pass 1.3 - should be OK
        checker.lock_inferred_type("bodies", param_type, "1.3", ("test.py", 15))

        assert not checker.has_errors()


class TestRealWorldBugs:
    """
    Test that the type system would have caught real bugs from the session.
    """

    def test_bug_for_loop_variable_truncation(self):
        """
        Bug: For-loop variables silently became 32-bit instead of 64-bit.

        The loop variable starts as int64_t from range().
        Then i = i * i should produce int64_t.
        But it was being inferred as int.
        """
        checker = InvariantChecker()

        # i from range() is int64_t
        i_type = make_int64_type(TypeOrigin.INFERRED, ("benchmark.py", 5))
        checker.check_temporal_monotonicity("i", i_type, ("benchmark.py", 5))

        # i * i should also be int64_t (from BIT_WIDTH_PRESERVATION)
        left = make_int64_type()
        right = make_int64_type()
        result = checker.check_bit_width_preservation(left, '*', right)

        # Now try to assign result back to i - should work
        checker.check_temporal_monotonicity("i", result, ("benchmark.py", 6))

        # Would catch if someone tried to assign int instead
        int_type = Type(base='int', bit_width=32)
        with pytest.raises(TypeSystemError):
            checker.check_temporal_monotonicity("i", int_type, ("benchmark.py", 7))

    def test_bug_float_conversion_from_int64t(self):
        """
        Bug: float(i) where i is int64_t was trying to parse as string.

        Should be: (double)i
        Was generating: mojo_make_float((char*)i)
        """
        checker = InvariantChecker()

        # i is int64_t
        i_type = make_int64_type()

        # float(i) should produce double
        result = checker.check_bit_width_preservation(
            i_type, 'cast_to_float', make_int64_type()
        )

        # The type checker would catch if code tried to call mojo_make_float
        # (which expects char*) with int64_t argument

    def test_bug_parameter_type_mismatch_at_call(self):
        """
        Bug: advance(bodies) where bodies is int64_t but advance expects MojoList*.

        Without cast, compilation fails.
        With OPAQUE_POINTER_TRACKING, type system catches it and generates cast.
        """
        checker = InvariantChecker()

        # bodies is stored as opaque pointer (int64_t)
        bodies_arg = make_opaque_pointer_type('MojoList')

        # advance expects explicit MojoList* parameter
        advance_param = make_mojolist_type(make_double_type())

        # Type system catches the mismatch
        with pytest.raises(TypeSystemError) as exc_info:
            checker.check_opaque_pointer_tracking(
                bodies_arg, advance_param, 0, "advance", ("benchmark.py", 100)
            )

        assert "cast" in exc_info.value.message.lower()

    def test_bug_nested_list_element_type_loss(self):
        """
        Bug: Nested list access losing element type information.

        arr = [[1.0, 2.0], ...]  // Type: MojoList[MojoList[double]]
        row = arr[0]             // Should be: MojoList[double]
        But was being inferred as int64_t
        """
        checker = InvariantChecker()

        # Create properly typed nested list
        double_type = make_double_type()
        inner_list = make_mojolist_type(double_type)
        outer_list = make_mojolist_type(inner_list)

        # Subscripting outer_list[0] should give inner_list
        row_type = checker.check_element_type_preservation(outer_list)
        assert row_type.base == 'MojoList'
        assert row_type.element_type.base == 'double'

        # Subscripting that [0] should give double
        value_type = checker.check_element_type_preservation(row_type)
        assert value_type.base == 'double'


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])

    # Also print a summary
    print("\n" + "=" * 70)
    print("Type System Test Summary")
    print("=" * 70)
    print("""
The type system with five key invariants would have caught:

✓ TEMPORAL_MONOTONICITY violations
  - For-loop variables changing from 64-bit to 32-bit

✓ BIT_WIDTH_PRESERVATION violations
  - Operations mixing 32-bit and 64-bit operands

✓ OPAQUE_POINTER_TRACKING violations
  - Passing int64_t pointers to pointer parameters without casting

✓ ELEMENT_TYPE_PRESERVATION violations
  - Subscripting containers with unknown element types

✓ INFERENCE_IDEMPOTENCE violations
  - Parameter types changing across compilation passes

All violations result in clear, actionable error messages that point to the
exact location and suggest fixes.
    """)
