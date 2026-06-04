# LP64 Pointer-in-Int Type Safety Audit

## Overview
The codebase intentionally stores pointers in `int64_t` to work around GIMPLE type restrictions, but does so unsafely. On LP64 systems, this requires:
1. Validated casts with hard throws on type mismatches
2. Type tracking dict synchronization validation
3. Runtime checks before pointer dereferences

## Critical Issues Found

### 1. **TypeLattice.coerce() - Unsafe Pointer Casting (gimple_codegen.py:137-144)**
```python
def coerce(self, val: str, from_type: str, to_type: str) -> str:
    ...
    if from_type != 'void *' and to_type == 'int64_t':
        return f"(int64_t)(void *){val}"  # UNSAFE: loses type info
```
**Problem**: Double-cast chain can lose pointer type information
**Fix Needed**: Validate pointer before casting; throw if type mismatch

### 2. **_lower_Name() - Global Pointer Storage (gimple_codegen.py:2690-2712)**
```python
if gtype.startswith(('MojoDict *', 'MojoList *', 'MojoSet *')):
    # At C level: int64_t global_var;
    # At Python level: int64_t should hold pointer
    c_code = f"(int64_t)(void *){gname}"
```
**Problem**: Separates C declaration type from actual pointer type. If `_actual_types[gname]` falls out of sync, silent corruption.
**Fix Needed**: Assert _actual_types[gname] exists and matches before casting

### 3. **_emit_call() - Argument Type Coercion (gimple_codegen.py:2053-2071)**
```python
if param_type == 'int64_t' and isinstance(arg_val, str) and arg_val in self._actual_types:
    # arg holds char*, MojoDict*, etc. but declared as int64_t
    cast_arg = f"(int64_t)(void *){arg_val}"  # UNSAFE
```
**Problem**: Blindly casts all arguments to int64_t without validating actual type
**Fix Needed**: Check _actual_types[arg_val] matches expected type before cast

### 4. **_lower_Subscript() - List Element Unboxing (gimple_codegen.py:6070-6073)**
```python
temp_str = f"__temp_str_{self.temp_var_count}"
self.temp_var_count += 1
gen.emit(f"{temp_str} = mojo_list_get_str ({list_val}, {idx_val});")
int_ptr = f"(int64_t){temp_str}"  # DANGEROUS: assumes char* in int64_t
```
**Problem**: Assumes list element is char* without checking list type
**Fix Needed**: Validate list element type before casting; throw if wrong

### 5. **_lower_MethodExpr() - Type Unboxing (gimple_codegen.py:3573-3581)**
```python
if ot and ot in ('MojoDict *', 'MojoList *', 'MojoSet *'):
    ip_cast = f"(int64_t){ov_local}"  # Convert to int64_t
    np_cast = f"({ot}){ip_cast}"      # Back to original pointer type
    # UNSAFE: No validation that ip_cast actually holds ot
```
**Problem**: Blind cast back to original type without verification
**Fix Needed**: Check _actual_types before casting; throw if type mismatch

### 6. **_gen_for_list() - Iterator Pointer Boxing (gimple_codegen.py:6135-6143)**
```python
temp_str = f"__temp_str_{self.temp_var_count}"
gen.emit(f"{temp_str} = mojo_list_get_str ({list_expr}, {idx_val});")
val_var = f"(int64_t){temp_str}"  # char* → int64_t
# Later: code assumes val_var holds a char* but it's int64_t
```
**Problem**: Doesn't track that this int64_t holds a char* pointer
**Fix Needed**: Ensure _actual_types[val_var] = 'char *' is set before use

### 7. **_gen_for_dict() - Dict Iterator Casting (gimple_codegen.py:6228-6232)**
```python
if it_val in self._actual_types and self._actual_types[it_val] == 'int64_t':
    dict_ptr = f"(MojoDict *){it_val}"  # DANGEROUS: assumes int64_t holds MojoDict*
    gen.emit(f"dict_len = mojo_dict_len ({dict_ptr});")
```
**Problem**: Casts opaque int64_t directly to MojoDict* without validation
**Fix Needed**: Verify _actual_types says this int64_t was originally MojoDict*

### 8. **_lower_ListComp() - List Comprehension Pointer Handling (gimple_codegen.py:4904-4907)**
```python
if isinstance(elem_expr, CallExpr) and elem_expr.func.name == 'mojo_list_get_str':
    # Returns char* but we store in int64_t
    int_ptr = f"(int64_t){temp_str}"  # UNSAFE
    gen0.target = int_ptr
```
**Problem**: Dynamically decides to box pointer without explicit type tracking
**Fix Needed**: Always set _actual_types[target] when boxing pointers

### 9. **_resolve_import_type() - Type Tracking Fragmentation (gimple_codegen.py:1759-1761)**
```python
_actual_types: dict[str, str] = {}           # var_name → actual type
_global_c_decl_types: dict[str, str] = {}    # var_name → C decl type
_global_var_types: dict[str, str] = {}       # var_name → runtime type
# PROBLEM: Must stay in perfect sync or type casts are silent UB
```
**Problem**: Three separate dicts that must be kept synchronized
**Fix Needed**: 
- Create unified type tracker
- Throw when accessing mismatched keys
- Validate consistency on type lookups

### 10. **File Handle Methods - Unvalidated int64_t as void* (gimple_codegen.py:3929-3944)**
```python
elif method == 'close':
    # Assumes ov (int64_t) holds valid file handle
    gen.emit(f"mojo_close((void *){ov});")  # NO VALIDATION
```
**Problem**: Treats int64_t as opaque handle without checking validity
**Fix Needed**: Assert _actual_types[ov] == 'file handle' or similar

### 11. **isinstance() Type ID Conversion - Double Cast Loss (gimple_codegen.py:4154-4159)**
```python
iv = f"(int64_t){obj_val}"
iv2 = f"(int){iv}"  # int64_t → int: LOSES DATA
gen.emit(f"_is_inst = mojo_isinstance ({iv2}, {type_id});")
```
**Problem**: int64_t → int cast loses 32 bits; may corrupt type ID
**Fix Needed**: Use int64_t directly or validate upper bits are 0

### 12. **Regex Match Methods - Unboxing (gimple_codegen.py:3841-3846)**
```python
if stored_type == 'int64_t':
    cstr_ov_temp = f"(char *){ov}"  # Direct int64_t → char* cast
    gen.emit(f"..._str = {cstr_ov_temp};")
```
**Problem**: Assumes int64_t contains valid char* without checking
**Fix Needed**: Assert _actual_types[ov] == 'char *' before cast

---

## Type Tracking Dictionary Issues

### Critical Synchronization Points
1. **When storing pointers as int64_t**: Must update `_actual_types[var] = 'ptr_type'`
2. **When casting back**: Must check `_actual_types[var]` before casting
3. **At variable scope boundaries**: Type info must be preserved through block nesting
4. **In loops/branches**: Type info must be consistent across all paths

### Currently No Validation
```python
# MISSING: No assertions like:
# assert var in self._actual_types, f"Type not tracked for {var}"
# assert self._actual_types[var] == expected_type, f"Type mismatch for {var}"
```

---

## Recommendations (Priority Order)

### P0 (Critical - Add Hard Throws)
1. **Add type tracking validation** before every pointer cast
   - Throw if variable not in `_actual_types`
   - Throw if actual type doesn't match expected cast

2. **Unify type tracking dicts** into single source of truth
   - Create `TypeInfo` namedtuple with all metadata
   - Access through validated getter that throws on mismatch

3. **Add casts with validation**:
   ```python
   def safe_cast_to_pointer(var: str, expected_type: str) -> str:
       if var not in self._actual_types:
           raise TypeError(f"Type not tracked for {var}")
       actual = self._actual_types[var]
       if actual != expected_type and actual != 'int64_t':
           raise TypeError(f"Type mismatch: {var} is {actual}, expected {expected_type}")
       return f"({expected_type}){var}"
   ```

### P1 (High - Validation Points)
- List subscript operations: validate element type before boxing
- Dict iteration: validate iterator actually holds dict pointer
- Method calls on boxed pointers: validate type before method dispatch
- isinstance() checks: use int64_t, don't truncate to int

### P2 (Medium - Documentation)
- Document which variables hold boxed pointers
- Add comments marking unsafe casts with rationale
- Create type tracking diagram for each function

---

## Files Affected
- **gimple_codegen.py**: Primary issue (12 major locations)
- **mojo.py**: Uses generated code
- **module_loader.py**: Module imports (indirect impact)

## Next Steps
1. Rebuild with audit findings
2. Add hard throws at identified locations
3. Run tests to see what breaks
4. Fix type tracking systematically
