# GIMPLE Closure Specification

Specification for lowering nested functions (closures) with captured variables to module-level C functions.

Source: Extracted from gimple_codegen.py closure pre-pass (lines 2702-2743), closure lifting (lines 2407-2447), and closure environment struct generation (lines 2825-2832).

---

## Overview

Closures in GIMPLE are implemented via **closure lifting**: nested functions are converted to module-level C functions with an implicit **environment pointer** parameter that carries captured variables.

**Approach**:
1. Analyze nested function for free variables (used but not defined locally)
2. Match free variables to outer scope to get their types
3. Create environment struct containing captured variables
4. Generate module-level C function with environment pointer as first parameter
5. Rewrite variable references to load from environment struct

---

## Example

### Mojo Source

```mojo
fn make_adder(n: Int) -> Int:
    fn adder(x: Int) -> Int:
        return x + n
    return adder(10)
```

### Closure Analysis

**Outer function `make_adder`**:
- Parameters: `n: Int`
- Local scope: `{n: int}`

**Inner function `adder`**:
- Parameters: `x: Int`
- Used variables: `{x, n}`
- Inner scope: `{x}`
- Free variables (used but not defined locally): `{n}`
- Captures from outer: `{(n, int)}`

### Generated C Code

**Environment struct** (1 captured variable):
```c
typedef struct make_adder_adder_env {
    int n;
} make_adder_adder_env;
```

**Lifted closure function** (environment pointer + original parameters):
```c
int __GIMPLE make_adder_adder (make_adder_adder_env * _env, int x)
{
  int _return;
  int _t1;
bb_2:
  _t1 = _env->n;       // Load captured 'n' from environment
  _t1 = _t1 + x;       // Compute x + n
  _return = _t1;
  return _return;
}
```

**Call site in outer function**:
```c
int __GIMPLE make_adder (int n)
{
  int _return;
  make_adder_adder_env *_env;
  void *_vp;
  int _t1;
bb_2:
  _vp = malloc(sizeof(make_adder_adder_env));
  _env = (make_adder_adder_env *)_vp;
  _env->n = n;         // Initialize environment with captured value
  _t1 = make_adder_adder(_env, 10);  // Call with environment pointer
  _return = _t1;
  return _return;
}
```

---

## Closure Lifting Algorithm

### Phase 1: Capture Analysis (Pre-pass)

For each nested FunctionDef:

1. **Build outer scope**: Collect parameter names and types from outer function
   ```
   outer_scope = {
       param1: param1_type,
       param2: param2_type,
       local_var: declared_type,
       ...
   }
   ```

2. **Analyze inner function**:
   - Collect **used** variables: identifiers referenced in inner body
   - Collect **declared** variables: parameters and assignments in inner function
   - Compute **free variables**: `free = used - declared - module_globals`

3. **Determine captures**:
   ```
   captures = [(var, type) for var in free if var in outer_scope]
   ```

4. **Create environment struct type**:
   - If `captures` is non-empty: generate struct `{lifted_name}_env`
   - If `captures` is empty: no struct (no environment needed)

### Example: Capture Analysis

Mojo code:
```mojo
fn outer(a: Int, b: Int):
    c: Int = 42
    def inner(x: Int):
        return x + a + c
```

Analysis:
- **Outer scope**: `{a: int, b: int, c: int}`
- **Used in inner**: `{x, a, c}`
- **Declared in inner**: `{x}`
- **Free variables**: `{a, c}`
- **Captures**: `[(a, int), (c, int)]`

Environment struct:
```c
typedef struct outer_inner_env {
    int a;
    int c;
} outer_inner_env;
```

---

## Closure Information Structure

### ClosureInfo Class

```python
class ClosureInfo:
    def __init__(self, lifted_name: str, env_struct: str, 
                 captures: list, inner_def):
        self.lifted_name = lifted_name      # e.g., "make_adder_adder"
        self.env_struct = env_struct        # e.g., "make_adder_adder_env" (empty if no captures)
        self.captures = captures            # [(var, ctype), ...] sorted by var name
        self.inner_def = inner_def          # Original FunctionDef node
```

### Example

For `make_adder.adder`:
```python
ClosureInfo(
    lifted_name="make_adder_adder",
    env_struct="make_adder_adder_env",
    captures=[("n", "int")],
    inner_def=<FunctionDef node for adder>
)
```

---

## Lifted Function Signature

### Signature Construction

For closure with captures:
```c
return_type __GIMPLE lifted_name (env_struct * _env, param1_type param1, param2_type param2, ...)
```

For closure without captures:
```c
return_type __GIMPLE lifted_name (param1_type param1, param2_type param2, ...)
```

### Examples

With captures:
```c
int __GIMPLE make_adder_adder (make_adder_adder_env * _env, int x)
```

Without captures (nested function with no free variables):
```c
int __GIMPLE outer_inner (int x, int y)
```

### Return Type Inference

If closure has explicit return type annotation, use it:
```mojo
def inner(x: Int) -> Float:
    return float(x)
```

Otherwise, infer from return statements in closure body.

---

## Variable Resolution in Closures

### Captured Variable Access

Inside closed-over function body, references to captured variables are rewritten to load from environment struct:

```
identifier 'n' → _env->n
identifier 'c' → _env->c
```

### Variable Categories in Closure Body

1. **Parameter** (local): Use directly
   ```c
   x + _env->n      // 'x' is parameter
   ```

2. **Captured** (from outer scope): Load from `_env`
   ```c
   _env->n          // 'n' is captured
   ```

3. **Local** (declared in closure): Use directly
   ```c
   int local_var;   // declared in closure body
   local_var = 42;
   ```

4. **Global** (module-level function or type): Resolve normally
   ```c
   printf("%d\n", local_var);  // 'printf' is global
   ```

---

## Closure Call Sites

### Closure Creation and Initialization

At call site, before calling closed-over function:

1. Allocate environment struct via malloc
2. Initialize struct fields with captured values
3. Store environment pointer in variable
4. Call closure function with environment pointer as first argument

### Example

```mojo
fn outer(a: Int):
    def inner(x: Int):
        return x + a
    return inner(5)
```

Generates:

```c
int __GIMPLE outer(int a) {
    int _return;
    outer_inner_env *_env;
    void *_vp;
    int _t1;
bb_2:
    _vp = malloc(sizeof(outer_inner_env));
    _env = (outer_inner_env *)_vp;
    _env->a = a;                          // Initialize capture
    _t1 = outer_inner(_env, 5);           // Call with environment
    _return = _t1;
    return _return;
}
```

### Multiple Closure Calls

If closure called multiple times, initialization may be deferred or environment reused:

```mojo
def outer(a: Int):
    def inner(x: Int) -> Int:
        return x + a
    r1 = inner(1)
    r2 = inner(2)
    return r1 + r2
```

Generates:

```c
int __GIMPLE outer(int a) {
    int _return;
    outer_inner_env *_env;
    int _t1, _t2, _t3;
bb_2:
    _env = (outer_inner_env *)malloc(sizeof(outer_inner_env));
    _env->a = a;                          // Initialize once
    _t1 = outer_inner(_env, 1);           // First call
    _t2 = outer_inner(_env, 2);           // Second call (reuse _env)
    _t3 = _t1 + _t2;
    _return = _t3;
    return _return;
}
```

---

## Nested Closures

Closures can be nested (closure containing closure).

### Example

```mojo
def outer(a: Int):
    def middle(b: Int):
        def inner(x: Int):
            return x + a + b
        return inner(5)
    return middle(10)
```

### Analysis

**Inner closure `inner`**:
- Free variables: `{x, a, b}`
- Outer scope (for `middle`): `{a, b}`
- Captures: `[(a, int), (b, int)]`
- Lifted name: `outer_middle_inner`
- Env struct: `outer_middle_inner_env`

**Middle closure `middle`**:
- Free variables: `{b, a}` (from `inner`)
- Outer scope (for `outer`): `{a}`
- Captures: `[(a, int)]`
- Lifted name: `outer_middle`
- Env struct: `outer_middle_env`

### Generated Code

```c
// Environment for innermost closure
typedef struct outer_middle_inner_env {
    int a;
    int b;
} outer_middle_inner_env;

// Environment for middle closure
typedef struct outer_middle_env {
    int a;
} outer_middle_env;

// Innermost lifted function
int __GIMPLE outer_middle_inner(outer_middle_inner_env * _env, int x) {
    int _return;
bb_2:
    _return = x + _env->a + _env->b;
    return _return;
}

// Middle lifted function
int __GIMPLE outer_middle(outer_middle_env * _env, int b) {
    int _return;
    outer_middle_inner_env *_inner_env;
    int _t1;
bb_2:
    _inner_env = (outer_middle_inner_env *)malloc(sizeof(outer_middle_inner_env));
    _inner_env->a = _env->a;              // From outer environment
    _inner_env->b = b;                    // From middle's parameter
    _t1 = outer_middle_inner(_inner_env, 5);
    _return = _t1;
    return _return;
}

// Outer function
int __GIMPLE outer(int a) {
    int _return;
    outer_middle_env *_env;
    int _t1;
bb_2:
    _env = (outer_middle_env *)malloc(sizeof(outer_middle_env));
    _env->a = a;
    _t1 = outer_middle(_env, 10);
    _return = _t1;
    return _return;
}
```

---

## Closure Without Captures

If nested function has no free variables, no environment struct is needed.

### Example

```mojo
def outer(a: Int):
    def inner(x: Int):
        return x + 1           # Uses only parameter 'x'
    return inner(5)
```

### Analysis

- Used: `{x}`
- Declared: `{x}`
- Free: `{}` (empty)
- Captures: `[]` (empty)
- Env struct: `""` (none)

### Generated Code

```c
int __GIMPLE outer_inner(int x) {          // No environment parameter
    int _return;
bb_2:
    _return = x + 1;
    return _return;
}

int __GIMPLE outer(int a) {
    int _return;
    int _t1;
bb_2:
    _t1 = outer_inner(5);                  // Call without environment
    _return = _t1;
    return _return;
}
```

---

## Closure Environment Memory Management

### Allocation

Environment structs are allocated on the heap via `malloc`:

```c
_env = (type_name_env *)malloc(sizeof(type_name_env));
```

### Initialization

After allocation, struct fields are initialized with captured values (copied by value):

```c
_env->captured_var = outer_var;
```

### Lifetime

Environment object remains allocated for the lifetime of closure usage. In simple cases, no explicit free is performed (leaking memory). For long-lived closures, explicit `free(_env)` would be needed.

### Future Enhancement

Could add reference counting or GC tracking for environment structs.

---

## Closure vs. Capture Semantics

### Capture by Value

Variables are captured by value (copied into environment struct):

```mojo
def outer(a: Int):
    def inner():
        return a
    a = 10
    return inner()   # Returns 10 (modified 'a' captured)
```

Generated C:
```c
outer_inner_env *_env = malloc(...);
_env->a = a;        // Copy current value of 'a'
```

This captures the **current value** at environment creation time, not a reference to the original variable.

### Future: Capture by Reference

Could support capture by reference with pointer indirection:

```c
typedef struct outer_inner_env {
    int *a;         // Pointer to outer's 'a'
} outer_inner_env;
```

---

## Limitations and Future Work

### Current Implementation

1. **Capture by value only**: No mutable reference capture
2. **No higher-order functions**: Closures cannot be returned as first-class values
3. **Single nesting level**: Nested closures work, but each closure captured by value
4. **No closure modification**: Captured variables are immutable in closure

### Future Enhancements

1. **First-class function values**: Store closure pointer + environment in struct
   ```c
   typedef struct {
       int (*func_ptr)(env_type *, args...);
       env_type *env;
   } Closure;
   ```

2. **Mutable captures**: Capture by reference using pointers
   ```c
   typedef struct outer_inner_env {
       int *a;  // Reference to outer's stack variable
   } outer_inner_env;
   ```

3. **Automatic cleanup**: Reference counting or GC for environments

4. **Partial application**: Pre-fill some closure arguments

5. **Continuation-passing style (CPS)**: For non-local control flow

---

## Integration with GIMPLE Codegen

### Pre-pass: Closure Detection

Before generating code, codegen performs three passes:
1. Collect function signatures (return types)
2. Collect struct field types
3. **Analyze nested functions and build closure info**

### Lift Generation

During module code generation:
1. Emit closure environment struct typedefs
2. Generate lifted functions via `_gen_lifted_closure()`
3. Register lifted function names in global scope

### Call Site Rewriting

When nested function is called, codegen:
1. Creates temporary for environment struct pointer
2. Allocates environment via implicit `_alloc_` helper
3. Initializes struct fields
4. Calls lifted function with environment as first parameter

---

**Specification Date**: 2026-04-28  
**Status**: Complete closure lifting specification for nested functions  
**Integration**: Referenced by gimple_codegen.py for nested function analysis and code generation
