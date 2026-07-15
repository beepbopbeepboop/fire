# Type System Coverage Audit

## Overview

This document audits where type system invariant checks are needed in gimple_codegen.py and which are currently covered.

## Critical Bug-Prone Areas

### 1. Variable Declaration (_declare_var)

**Pattern**: New variables assigned types
**Bug Risk**: HIGH - Initial type sets the pattern for lifetime
**Locations**: Lines 2726, 3185, 5832, 5892, 5928, 5971, 5996, 6020, 6210, 6224, 6246, 6278, 6301
**Invariants**: TEMPORAL_MONOTONICITY (locks initial type)
**Status**: ⚠️ NEEDS AUDIT

```python
def _declare_var(self, name: str, ctype: str, elem: str | None = None):
    # TYPE CHECK: First assignment should be locked for TEMPORAL_MONOTONICITY
    # Need to verify ctype is consistent with inferred types
```

**Action**: Add type checking to verify initial type matches inference

---

### 2. Type Coercion (_safe_coerce_emit)

**Pattern**: Converting between types (src → dst)
**Bug Risk**: CRITICAL - Silent truncation, wrong function calls
**Locations**: Lines 2528, 3187, 3261, 3265, 3417, 3427, 3736, 3740, 4567, 5439, 5445, 6221, 6248, 6280
**Invariants**: BIT_WIDTH_PRESERVATION, TEMPORAL_MONOTONICITY
**Status**: ❌ NOT CHECKED

```python
def _safe_coerce_emit(self, src: str, dst: str, val: str, lhs: str) -> None:
    # TYPE CHECKS NEEDED:
    # 1. BIT_WIDTH_PRESERVATION: Check src/dst bit widths compatible
    # 2. TEMPORAL_MONOTONICITY: Verify coercion preserves type invariants
    # 3. OPAQUE_POINTER_TRACKING: If src/dst are pointers, tag appropriately
```

**Action**: Add comprehensive type checking before every coercion

---

### 3. For Loop Variable Handling

**Pattern**: Loop variables get element types
**Bug Risk**: CRITICAL - Loop var type mismatches (int64_t vs int)
**Locations**: Lines 5832-5971 (_gen_for_range, _gen_for_list_simple, etc.)
**Invariants**: TEMPORAL_MONOTONICITY, BIT_WIDTH_PRESERVATION, ELEMENT_TYPE_PRESERVATION
**Status**: ⚠️ PARTIAL - Basic loops ok, nested loops need audit

```python
def _gen_for_range(self, node):
    # LINE 5832: i declared as 'int' - should be 'int64_t'
    # CURRENT: self._declare_var(gen0.target, 'int')
    # SHOULD BE: self._declare_var(gen0.target, 'int64_t')
    # Also need type checking for nested structures
```

**Action**: Verify all loop variables use int64_t, add nested container handling

---

### 4. List Element Type Propagation

**Pattern**: Subscripts return element types
**Bug Risk**: HIGH - Wrong function calls if element type lost
**Locations**: Lines 5450-5600 (_lower_subscript)
**Invariants**: ELEMENT_TYPE_PRESERVATION
**Status**: ⚠️ PARTIAL - Basic checking in place, complex cases need audit

```python
def _lower_subscript(self, node: SubscriptExpr):
    # CURRENT: Type checking hook at line 5455
    # NEEDS: Deeper tracking of nested element types
    # MISSING: Verification that element type is correct for all operations
```

**Action**: Add comprehensive element type verification for all container ops

---

### 5. Function Call Parameter Passing

**Pattern**: Arguments passed to parameters
**Bug Risk**: CRITICAL - Type mismatches, opaque pointer casting
**Locations**: Lines 2349+ (_emit_call), every function call site
**Invariants**: OPAQUE_POINTER_TRACKING, BIT_WIDTH_PRESERVATION
**Status**: ⚠️ PARTIAL - Basic checking added, needs comprehensive coverage

```python
def _emit_call(self, ret_type, result_var, fname, arg_pairs):
    # CURRENT: Type checking at lines 2366+ for opaque pointers
    # NEEDS: Check every argument position for type safety
    # MISSING: Verify bit widths of numeric arguments
```

**Action**: Expand checking to cover all argument positions and types

---

### 6. Ternary Expression Type Handling

**Pattern**: if-then-else type selection
**Bug Risk**: MEDIUM - Type mismatch between branches
**Locations**: Lines 3240-3275 (_lower_TernaryExpr)
**Invariants**: TEMPORAL_MONOTONICITY, BIT_WIDTH_PRESERVATION
**Status**: ❌ NOT CHECKED

```python
def _lower_TernaryExpr(self, node):
    # TYPE CHECKS NEEDED:
    # Verify true_type and false_type are compatible
    # Check result type is appropriate for both branches
```

**Action**: Add type checking for ternary expressions

---

### 7. Member Access Type Inference

**Pattern**: Struct field access
**Bug Risk**: MEDIUM - Wrong types for fields
**Locations**: Lines 3266-3380 (_lower_MemberExpr)
**Invariants**: All (struct fields should have known types)
**Status**: ⚠️ PARTIAL - Field type lookup works, validation missing

```python
def _lower_MemberExpr(self, node):
    # TYPE CHECKS NEEDED:
    # Verify field type from struct_field_types matches usage
    # Validate accessed field exists with right type
```

**Action**: Add struct field type validation

---

### 8. List/Dict Literal Creation

**Pattern**: [1, 2, 3] creates container with element type
**Bug Risk**: HIGH - Wrong element type inferred
**Locations**: Lines 5200-5600 (_lower_list, _lower_dict, etc.)
**Invariants**: ELEMENT_TYPE_PRESERVATION, INFERENCE_IDEMPOTENCE
**Status**: ⚠️ PARTIAL - Element type inference works, validation missing

```python
def _lower_ListLiteral(self, node):
    # TYPE CHECKS NEEDED:
    # Verify all elements have consistent types
    # Lock element type for INFERENCE_IDEMPOTENCE
```

**Action**: Add element type consistency checking

---

### 9. Variable Type Inference During Assignment

**Pattern**: x = expr infers type of x from expr
**Bug Risk**: CRITICAL - Type inference gets wrong type
**Locations**: Lines 6200-6320 (_gen_stmt_AssignStmt)
**Invariants**: TEMPORAL_MONOTONICITY, INFERENCE_IDEMPOTENCE
**Status**: ✅ CHECKED (type checking added at line 6277)

---

### 10. Return Type Consistency

**Pattern**: return expr in function
**Bug Risk**: MEDIUM - Return type inconsistent with annotation
**Locations**: Lines 2813-2817 (_infer_return_type)
**Invariants**: INFERENCE_IDEMPOTENCE
**Status**: ✅ CHECKED (locking added for return types)

---

### 11. Binary Operation Type Results

**Pattern**: x + y produces type based on x, y types
**Bug Risk**: CRITICAL - Wrong result type for arithmetic
**Locations**: Lines 3684-3750 (_lower_binary arithmetic section)
**Invariants**: BIT_WIDTH_PRESERVATION, INFERENCE_IDEMPOTENCE
**Status**: ⚠️ PARTIAL - Basic checking at line 3695, needs coverage of all ops

```python
# CURRENT: Checks at line 3695 for +, -, *, /, %
# MISSING: Checks for // (floor div), ** (pow), other binary ops
# MISSING: Verify result type is correct for all cases
```

**Action**: Add comprehensive binary operation type checking

---

### 12. Unary Operation Type Results

**Pattern**: -x, not x produces type based on x type
**Bug Risk**: MEDIUM - Wrong unary result type
**Locations**: Need to find _lower_UnaryOp
**Invariants**: BIT_WIDTH_PRESERVATION
**Status**: ❌ NOT AUDITED YET

---

### 13. Type Inference for Numeric Literals

**Pattern**: 1 → int64_t, 1.0 → double
**Bug Risk**: LOW (but validates baseline)
**Locations**: Lines 2917-2928 (_lower_IntLiteral, _lower_FloatLiteral)
**Invariants**: INFERENCE_IDEMPOTENCE
**Status**: ⚠️ PARTIAL - Types hardcoded, should validate

---

### 14. String Literal Type Handling

**Pattern**: "hello" → char *
**Bug Risk**: MEDIUM - Type confusion between strings and ints
**Locations**: Lines 2935-3080 (string literal handling)
**Invariants**: TEMPORAL_MONOTONICITY, OPAQUE_POINTER_TRACKING
**Status**: ⚠️ PARTIAL - String types tracked, validation missing

---

### 15. Cast Operations

**Pattern**: (int64_t)x, (double)y, (char *)x
**Bug Risk**: CRITICAL - Invalid casts, pointer type confusion
**Locations**: Lines 4800+ (_lower_cast, various cast sites)
**Invariants**: BIT_WIDTH_PRESERVATION, OPAQUE_POINTER_TRACKING
**Status**: ❌ NOT CHECKED

```python
# TYPE CHECKS NEEDED:
# 1. Source and destination types compatible
# 2. Casting preserves bit width or is explicit
# 3. Pointer casts properly tag opaque pointers
```

**Action**: Add comprehensive cast validation

---

### 16. Function Return Type Annotation

**Pattern**: def foo() -> int64_t: ... 
**Bug Risk**: MEDIUM - Annotation vs inferred type mismatch
**Locations**: Lines 8140-8220 (return type annotation handling)
**Invariants**: INFERENCE_IDEMPOTENCE
**Status**: ⚠️ PARTIAL - Types stored, consistency check missing

---

### 17. Parameter Type Annotation

**Pattern**: def foo(x: int64_t): ...
**Bug Risk**: HIGH - Parameter type inferred wrong but annotation ignored
**Locations**: Lines 8090-8180 (parameter type handling)
**Invariants**: INFERENCE_IDEMPOTENCE, BIT_WIDTH_PRESERVATION
**Status**: ⚠️ PARTIAL - Types stored, consistency check missing

---

## Summary of Coverage

| Location | Bug Risk | Current Status | Action Required |
|----------|----------|-----------------|-----------------|
| _declare_var | HIGH | ⚠️ Partial | Add initial type locking |
| _safe_coerce_emit | CRITICAL | ❌ None | Add comprehensive checking |
| For loops | CRITICAL | ⚠️ Partial | Verify int64_t usage |
| List subscripts | HIGH | ⚠️ Partial | Enhance element tracking |
| Function calls | CRITICAL | ⚠️ Partial | Expand parameter checking |
| Ternary expr | MEDIUM | ❌ None | Add branch type checking |
| Member access | MEDIUM | ⚠️ Partial | Add field validation |
| List literals | HIGH | ⚠️ Partial | Lock element types |
| Variable assign | CRITICAL | ✅ Done | No action |
| Return types | MEDIUM | ✅ Done | No action |
| Binary ops | CRITICAL | ⚠️ Partial | Expand to all ops |
| Unary ops | MEDIUM | ❌ None | Add checking |
| Numeric literals | LOW | ⚠️ Partial | Validate types |
| String literals | MEDIUM | ⚠️ Partial | Add validation |
| Cast operations | CRITICAL | ❌ None | Add validation |
| Return annotation | MEDIUM | ⚠️ Partial | Add consistency check |
| Parameter annotation | HIGH | ⚠️ Partial | Add consistency check |

## Recommendations

**Priority 1 (Critical)**: 
- Add type checking to _safe_coerce_emit
- Add cast operation validation
- Verify all binary operations checked
- Expand function call parameter checking

**Priority 2 (High)**:
- List literal element type locking
- For loop variable type verification
- Member access field type validation
- Parameter annotation consistency

**Priority 3 (Medium)**:
- Ternary expression type checking
- String literal type validation
- Return type annotation consistency

## Next Steps

1. Add comprehensive type checking to _safe_coerce_emit
2. Audit and enhance binary operation coverage
3. Add cast operation validation
4. Verify for-loop variable types
5. Run comprehensive test suite with type checking enabled
