"""
Type System for Mojo Compiler

Implements rich type representation and invariant checking to catch:
- TEMPORAL_MONOTONICITY: Variables don't change types mid-program
- BIT_WIDTH_PRESERVATION: 64-bit operations stay 64-bit
- OPAQUE_POINTER_TRACKING: int64_t pointers explicitly cast
- ELEMENT_TYPE_PRESERVATION: Container element types flow through operations
- INFERENCE_IDEMPOTENCE: Type inference completes before code generation
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Set, Tuple, Any
from enum import Enum


class TypeOrigin(Enum):
    """Where a type came from"""
    ANNOTATED = "annotated"      # User wrote the type
    INFERRED = "inferred"        # Inferred from usage/assignments
    LITERAL = "literal"          # From a literal value
    CAST = "cast"                # From an explicit cast
    DEFAULT = "default"          # Default (int64_t, etc.)


@dataclass
class Type:
    """
    Complete type information for values.

    This represents both the C-level representation and the semantic type.
    """
    base: str                          # 'int64_t', 'double', 'MojoList', etc.

    # Bit width tracking - crucial for BIT_WIDTH_PRESERVATION
    bit_width: Optional[int] = None    # 32, 64, or None for non-numeric

    # Pointer semantics - crucial for OPAQUE_POINTER_TRACKING
    is_pointer: bool = False           # Is this a pointer value?
    pointer_to: Optional['Type'] = None  # What does it point to?
    is_opaque_pointer: bool = False    # Stored as int64_t?

    # Numeric properties
    is_signed: bool = True             # int64_t vs uint64_t

    # Container element types - crucial for ELEMENT_TYPE_PRESERVATION
    element_type: Optional['Type'] = None        # What's in the container?
    nested_element_type: Optional['Type'] = None # For lists of lists

    # Type origin (for error messages)
    origin: TypeOrigin = TypeOrigin.DEFAULT
    origin_loc: Optional[Tuple[str, int]] = None  # (file, line)

    # For tracking which inference pass assigned this
    inferred_at_pass: Optional[str] = None  # "1.2", "1.3b", etc.

    def __str__(self) -> str:
        """Human-readable type representation"""
        if self.is_opaque_pointer:
            return f"int64_t<opaque->{self.base}*>"

        if self.element_type:
            elem_str = str(self.element_type)
            if self.nested_element_type:
                nested_str = str(self.nested_element_type)
                return f"{self.base}[{self.base}[{nested_str}]]"
            return f"{self.base}[{elem_str}]"

        if self.is_pointer:
            return f"{self.base}*"

        if self.bit_width:
            return f"{self.base}({self.bit_width}-bit)"

        return self.base

    def __eq__(self, other: Any) -> bool:
        """Check if two types are equivalent"""
        if not isinstance(other, Type):
            return False

        # Check all essential properties
        return (
            self.base == other.base
            and self.bit_width == other.bit_width
            and self.is_pointer == other.is_pointer
            and self.is_opaque_pointer == other.is_opaque_pointer
            and self.is_signed == other.is_signed
            and self.element_type == other.element_type
            and self.nested_element_type == other.nested_element_type
        )

    def is_numeric(self) -> bool:
        """Is this a numeric type?"""
        return self.base in ('int', 'int64_t', 'uint64_t', 'double', 'float', '_Bool')

    def is_container(self) -> bool:
        """Is this a container type?"""
        return self.base in ('MojoList', 'MojoDict', 'MojoSet')

    def is_64bit(self) -> bool:
        """Is this a 64-bit type?"""
        return self.bit_width == 64 or self.base in ('int64_t', 'uint64_t', 'double')

    def is_32bit(self) -> bool:
        """Is this a 32-bit type?"""
        return self.bit_width == 32 or self.base in ('int', 'float', '_Bool')


class TypeSystemError(Exception):
    """Type system invariant violation"""
    def __init__(self, invariant: str, message: str, location: Optional[Tuple[str, int]] = None):
        self.invariant = invariant
        self.message = message
        self.location = location
        loc_str = f"{location[0]}:{location[1]}: " if location else ""
        super().__init__(f"{loc_str}VIOLATION: {invariant}\n{message}")


class InvariantChecker:
    """
    Checks the five key type system invariants.

    Each invariant has a check method that raises TypeSystemError on violation.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.variable_types: Dict[str, Type] = {}  # Track types over time
        self.locked_types: Set[str] = set()        # Types locked for INFERENCE_IDEMPOTENCE
        self.error_log: list = []

    # ─── INVARIANT 1: TEMPORAL_MONOTONICITY ─────────────────────────────────

    def check_temporal_monotonicity(
        self,
        var_name: str,
        new_type: Type,
        location: Optional[Tuple[str, int]] = None
    ) -> None:
        """
        Once a variable is assigned a type, it cannot silently change to a different type.

        Violation: int64_t variable becoming int implicitly
        """
        if var_name not in self.variable_types:
            # First assignment - record the type
            self.variable_types[var_name] = new_type
            return

        old_type = self.variable_types[var_name]

        # Check if types are compatible
        if not self._is_compatible_assignment(old_type, new_type):
            raise TypeSystemError(
                "TEMPORAL_MONOTONICITY",
                f"""
Variable '{var_name}' type changed incompatibly:
  Previous type: {old_type} (origin: {old_type.origin.value} at {old_type.origin_loc})
  Assigned type: {new_type} (origin: {new_type.origin.value} at {new_type.origin_loc})

Type system requires that variables maintain their bit width and structure once assigned.
This prevents silent truncation (int64_t → int) or type confusion.

Possible fixes:
  1. Use explicit cast: var = (int64_t)expression
  2. Use different variable for different type
  3. Ensure all assignments maintain type consistency
                """,
                location
            )

        # Update to new type (should be same or supertype)
        self.variable_types[var_name] = new_type

    def _is_compatible_assignment(self, old_type: Type, new_type: Type) -> bool:
        """Check if assignment is compatible with TEMPORAL_MONOTONICITY"""
        # Exact match is always OK
        if old_type == new_type:
            return True

        # Widening is OK (int → int64_t)
        if old_type.is_32bit() and new_type.is_64bit():
            return True

        # Same base type with different bit width is OK if widening
        if old_type.base == new_type.base:
            if old_type.bit_width and new_type.bit_width:
                if old_type.bit_width <= new_type.bit_width:
                    return True

        # Both are opaque pointers to same type is OK
        if (old_type.is_opaque_pointer and new_type.is_opaque_pointer
            and old_type.base == new_type.base):
            return True

        return False

    # ─── INVARIANT 2: BIT_WIDTH_PRESERVATION ────────────────────────────────

    def check_bit_width_preservation(
        self,
        left_type: Type,
        op: str,
        right_type: Type,
        location: Optional[Tuple[str, int]] = None
    ) -> Type:
        """
        64-bit operations cannot produce 32-bit results.
        32-bit operations cannot receive 64-bit inputs without explicit casting.

        Returns the result type of the operation.
        """
        # Check bit width compatibility
        if left_type.is_numeric() and right_type.is_numeric():
            left_64 = left_type.is_64bit()
            right_64 = right_type.is_64bit()

            # Mixing 32 and 64 bit
            if left_64 != right_64:
                raise TypeSystemError(
                    "BIT_WIDTH_PRESERVATION",
                    f"""
Cannot perform {op} on mismatched bit widths:
  Left:  {left_type} ({left_type.bit_width}-bit)
  Right: {right_type} ({right_type.bit_width}-bit)

In Mojo's ABI, integers are 64-bit (int64_t) and should maintain that width.
Mixing 32-bit and 64-bit operands requires explicit casting.

Example fix:
  result = (int64_t)x + (int64_t)y  // Explicit widening cast
                    """,
                    location
                )

        # Determine result type
        result_type = self._infer_binary_op_result(left_type, op, right_type)
        return result_type

    def _infer_binary_op_result(self, left: Type, op: str, right: Type) -> Type:
        """Infer result type of binary operation"""
        # Arithmetic operations
        if op in ('+', '-', '*', '/'):
            # int64_t + int64_t → int64_t
            if left.is_64bit() and right.is_64bit():
                return Type(base='int64_t', bit_width=64, origin=TypeOrigin.INFERRED)
            # double + double → double
            if left.base == 'double' and right.base == 'double':
                return Type(base='double', bit_width=64, origin=TypeOrigin.INFERRED)

        # Comparison operations → bool
        if op in ('<', '>', '==', '!=', '<=', '>='):
            return Type(base='_Bool', bit_width=1, origin=TypeOrigin.INFERRED)

        # Default: return left type
        return left

    # ─── INVARIANT 3: OPAQUE_POINTER_TRACKING ──────────────────────────────

    def check_opaque_pointer_tracking(
        self,
        arg_type: Type,
        param_type: Type,
        arg_index: int,
        func_name: str,
        location: Optional[Tuple[str, int]] = None
    ) -> None:
        """
        When int64_t is used to store a pointer, it must be:
        1. Explicitly tagged as opaque_pointer
        2. Converted back to pointer type before use
        3. Never used as a numeric value

        Violation: Passing int64_t opaque pointer without explicit cast to pointer parameter
        """
        # If argument is opaque pointer but parameter expects explicit pointer, need cast
        if (arg_type.is_opaque_pointer and
            param_type.is_pointer and
            not param_type.is_opaque_pointer):

            raise TypeSystemError(
                "OPAQUE_POINTER_TRACKING",
                f"""
Argument {arg_index} of {func_name}():
Cannot pass opaque pointer {arg_type} to parameter expecting {param_type}

Opaque pointers (int64_t used to store pointer values) must be explicitly
converted back to their proper pointer type before use.

Generated code should include:
  _t_temp = ({param_type.base})(_t_arg_value);
  {func_name}(_t_temp, ...);
                """,
                location
            )

        # If parameter expects opaque pointer, argument should be int64_t
        if (param_type.is_opaque_pointer and
            not arg_type.is_opaque_pointer and
            arg_type.is_pointer):

            raise TypeSystemError(
                "OPAQUE_POINTER_TRACKING",
                f"""
Argument {arg_index} of {func_name}():
Passing explicit pointer {arg_type} where opaque pointer expected

Parameters expecting opaque pointers should receive int64_t with is_opaque_pointer=True.
                """,
                location
            )

    # ─── INVARIANT 4: ELEMENT_TYPE_PRESERVATION ───────────────────────────

    def check_element_type_preservation(
        self,
        container_type: Type,
        location: Optional[Tuple[str, int]] = None
    ) -> Type:
        """
        Container element types must flow through operations.

        Violation: Subscripting a list without knowing element type
        """
        if not container_type.is_container():
            return container_type

        if container_type.element_type is None:
            raise TypeSystemError(
                "ELEMENT_TYPE_PRESERVATION",
                f"""
Cannot subscript {container_type}:
Element type information is missing!

Container types (MojoList, MojoDict, etc.) must have element type information
tracked through all operations. This prevents losing type information when
accessing nested structures.

Possible causes:
  1. Element type not inferred during list creation
  2. Element type lost during assignment or operation
  3. Type inference incomplete for this container

To fix: Ensure element types are explicitly tracked through:
  - List literals: Type inference from initial elements
  - Subscript access: Return element type
  - Container operations: Propagate element types
                """,
                location
            )

        return container_type.element_type

    def propagate_element_type(
        self,
        container: Type,
        result_temp: str,
        location: Optional[Tuple[str, int]] = None
    ) -> Type:
        """
        When accessing a container element, propagate the element type to result.

        Example: arr[0] → element type should flow to arr[0]'s result type
        """
        if not container.is_container():
            return container

        elem_type = self.check_element_type_preservation(container, location)

        # Track that result_temp has element type
        if result_temp:
            self.variable_types[result_temp] = elem_type

        return elem_type

    # ─── INVARIANT 5: INFERENCE_IDEMPOTENCE ───────────────────────────────

    def lock_inferred_type(
        self,
        var_name: str,
        type_obj: Type,
        pass_name: str,
        location: Optional[Tuple[str, int]] = None
    ) -> None:
        """
        Lock in a type after inference completes. Later inferences must match.

        Used for parameter types, return types - once inferred in Pass 1.2/1.3,
        they must not change.
        """
        key = (var_name, pass_name)

        if var_name in self.locked_types:
            # Already locked - check it matches
            existing = self.variable_types.get(var_name)
            if existing and existing != type_obj:
                raise TypeSystemError(
                    "INFERENCE_IDEMPOTENCE",
                    f"""
Type inference for '{var_name}' produced different results!

First inference (Pass {existing.inferred_at_pass}):
  {existing}

Second inference (Pass {pass_name}):
  {type_obj}

Type inference must complete in a single pass and produce consistent results.
Multiple inference passes with different results indicate:
  1. Forward references affecting earlier inference
  2. Incomplete information during first pass
  3. Inference logic depends on order of operations

Fix: Ensure all inference happens in correct order (Phase 1 before Phase 2).
                    """,
                    location
                )
        else:
            self.locked_types.add(var_name)
            self.variable_types[var_name] = type_obj
            type_obj.inferred_at_pass = pass_name

    # ─── Utility methods ────────────────────────────────────────────────────

    def report_error(self, error: TypeSystemError) -> None:
        """Log a type system error"""
        self.error_log.append(error)
        if self.verbose:
            print(f"Type Error: {error}")

    def has_errors(self) -> bool:
        """Check if any invariants were violated"""
        return len(self.error_log) > 0

    def format_errors(self) -> str:
        """Format all accumulated errors"""
        if not self.error_log:
            return "✓ All type invariants satisfied"

        output = f"\n{'=' * 70}\nTYPE SYSTEM VIOLATIONS ({len(self.error_log)} errors)\n{'=' * 70}\n"
        for i, error in enumerate(self.error_log, 1):
            output += f"\n{i}. {error.invariant}\n{error.message}\n"
        return output


# ─── Helper functions for type construction ───────────────────────────────

def make_int64_type(origin: TypeOrigin = TypeOrigin.DEFAULT,
                   origin_loc: Optional[Tuple[str, int]] = None) -> Type:
    """Create an int64_t type"""
    return Type(
        base='int64_t',
        bit_width=64,
        is_signed=True,
        origin=origin,
        origin_loc=origin_loc
    )


def make_double_type(origin: TypeOrigin = TypeOrigin.DEFAULT,
                    origin_loc: Optional[Tuple[str, int]] = None) -> Type:
    """Create a double type"""
    return Type(
        base='double',
        bit_width=64,
        origin=origin,
        origin_loc=origin_loc
    )


def make_mojolist_type(element_type: Type,
                      origin: TypeOrigin = TypeOrigin.DEFAULT,
                      origin_loc: Optional[Tuple[str, int]] = None) -> Type:
    """Create a MojoList type with element type"""
    return Type(
        base='MojoList',
        is_pointer=True,
        element_type=element_type,
        origin=origin,
        origin_loc=origin_loc
    )


def make_opaque_pointer_type(pointing_to: str,
                            origin: TypeOrigin = TypeOrigin.DEFAULT,
                            origin_loc: Optional[Tuple[str, int]] = None) -> Type:
    """Create an opaque pointer (int64_t storage of pointer)"""
    return Type(
        base=pointing_to,
        bit_width=64,
        is_pointer=True,
        is_opaque_pointer=True,
        origin=origin,
        origin_loc=origin_loc
    )
