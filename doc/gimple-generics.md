# GIMPLE Generics Specification

Specification for handling Mojo generic type parameters and their lowering to C.

Source: Extracted from gimple_codegen.py type resolution (lines 375-398) and planned generic support.

---

## Overview

Generic types in Mojo allow parameterization over types:

```mojo
struct Stack[T]:
    data: List[T]
    len: Int
    
    fn push(value: T):
        data.append(value)

fn max[T](a: T, b: T) -> T:
    if a > b:
        return a
    return b
```

GIMPLE does not support generics directly. C is monomorphic. The strategy is **monomorphization**: for each concrete type parameter instantiation, generate a specialized C function.

---

## Current State

### Parameterized Type Extraction

Current implementation extracts the base type and parameters but discards them for type lowering:

```python
def _mojo_type(ann) -> str:
    if '[' in ann:
        base, rest = ann.split('[', 1)
        inner = rest.rstrip(']').strip()
        
        # Dispatch by base type
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            elem = _mojo_type(inner)
            return f"{elem} *"
        if base in ('List', 'InlineArray'):
            return 'MojoList *'    # Generic List[T] → MojoList *
        if base == 'Dict':
            return 'MojoDict *'
        if base == 'Set':
            return 'MojoSet *'
        if base == 'Optional':
            return _mojo_type(inner)  # Treat Optional[T] as T
```

**Limitation**: Type parameter `T` is **erased**. `List[Int]` and `List[Float]` both become `MojoList *`, losing type information.

### Implications

1. **No type-specific code generation**: Cannot generate `List[Int]` as array-of-int
2. **Runtime dispatch needed**: Container functions like `mojo_list_append_int()` use type suffixes determined at runtime
3. **No compile-time monomorphization**: Same code for all type instantiations

---

## Monomorphization Strategy

### Approach 1: Generic Function Specialization

For generic functions, generate one C function per concrete type instantiation.

#### Mojo Generic Function

```mojo
fn max[T](a: T, b: T) -> T:
    if a > b:
        return a
    return b
```

#### Usage

```mojo
result1 = max[Int](10, 20)       # Instantiate max[Int]
result2 = max[Float](3.5, 2.1)   # Instantiate max[Float]
```

#### Generated C Code

Two specialized functions:

```c
int __GIMPLE max_Int (int a, int b)
{
  int _return;
bb_2:
  _cond = a > b;
  if (_cond) goto bb_3; else goto bb_4;
bb_3:
  _return = a;
  goto bb_5;
bb_4:
  _return = b;
  goto bb_5;
bb_5:
  return _return;
}

double __GIMPLE max_Double (double a, double b)
{
  double _return;
bb_2:
  _cond = a > b;
  if (_cond) goto bb_3; else goto bb_4;
bb_3:
  _return = a;
  goto bb_5;
bb_4:
  _return = b;
  goto bb_5;
bb_5:
  return _return;
}
```

### Approach 2: Generic Struct Specialization

For generic structs, generate one struct definition per type instantiation.

#### Mojo Generic Struct

```mojo
struct Stack[T]:
    data: List[T]
    len: Int
    
    fn push(value: T):
        self.data.append(value)
```

#### Usage

```mojo
int_stack: Stack[Int]
float_stack: Stack[Float]
```

#### Generated C Code

Two specialized structs:

```c
// Stack[Int] specialization
typedef struct {
    MojoList *data;   // List[Int] → MojoList *
    int len;
} Stack_Int;

// Stack[Float] specialization
typedef struct {
    MojoList *data;   // List[Float] → MojoList *
    int len;
} Stack_Float;

// Methods for Stack_Int
void __GIMPLE Stack_Int_push (Stack_Int *self, int value)
{
bb_2:
  mojo_list_append_int(self->data, value);
  return;
}

// Methods for Stack_Float
void __GIMPLE Stack_Float_push (Stack_Float *self, double value)
{
bb_2:
  mojo_list_append_double(self->data, value);
  return;
}
```

### Approach 3: Constrained Generics (Where Clauses)

Generic functions can be constrained:

```mojo
fn process[T where conforms_to(T, Numeric)](value: T) -> T:
    return value + 1
```

**Constraint**: `T` must support `+` operator (conform to `Numeric` trait).

#### GIMPLE Handling

In GIMPLE, check constraints at specialization time. If type doesn't support required operations, specialization fails.

```
Specializing process[String]:
  Error: String does not conform to Numeric
```

---

## Generic Type Parameter Tracking

### Implementation

Track generic parameters through compilation:

```python
class GimpleGen:
    def __init__(self):
        self.generic_specs: dict[str, list[str]] = {}
        # func_name -> [(type_arg_1, ...), ...]
        # e.g., "max" -> [("Int",), ("Float",), ...]
```

### Collection Phase

During parsing/codegen, collect all specializations:

```python
# When visiting max[Int](10, 20):
# 1. Identify generic function "max"
# 2. Record instantiation "max[Int]"
# 3. Add to generic_specs

# When visiting max[Float](3.5, 2.1):
# 1. Identify generic function "max"
# 2. Record instantiation "max[Float]"
# 3. Add to generic_specs
```

### Specialization Generation

For each recorded specialization, generate code:

```python
for func_name, instantiations in generic_specs.items():
    for type_args in instantiations:
        # Generate specialized function
        specialized_name = f"{func_name}_{'_'.join(type_args)}"
        generate_function(func_name, type_args, specialized_name)
```

---

## Generic Method Dispatch

### Trait-Based Generics

Generic functions may dispatch on trait implementations:

```mojo
trait Numeric:
    fn add(self, other: Self) -> Self
    fn multiply(self, scalar: Float) -> Self

fn scale[T where conforms_to(T, Numeric)](value: T, factor: Float) -> T:
    return value.multiply(factor)
```

#### Monomorphization

For each specialization, resolve method calls to concrete implementations:

```
scale[Int]:
  T = Int
  value.multiply(factor)
    → Int_multiply(value, factor)  # Resolve to concrete method

scale[Vector]:
  T = Vector
  value.multiply(factor)
    → Vector_multiply(value, factor)  # Resolve to concrete method
```

---

## Type Parameter Erasure vs. Monomorphization

### Erasure (Current Approach)

Type parameters are **dropped** during lowering:

```
List[Int] → MojoList *
List[Float] → MojoList *
```

**Pros**:
- Minimal code generation
- Single runtime implementation

**Cons**:
- No type information at runtime
- Runtime type checks required
- Less efficient code generation

### Monomorphization (Proposed)

Type parameters are **preserved** during lowering; generate specialized code:

```
List[Int] → specialized_list_int (custom type, custom functions)
List[Float] → specialized_list_float (custom type, custom functions)
```

**Pros**:
- Full type information in generated code
- Compiler can inline and optimize per-type
- No runtime type checks

**Cons**:
- Larger code size (one copy per specialization)
- Slower compilation (generate more code)
- Code duplication

---

## Specialization Namespace

### Naming Scheme

Specialized functions use a deterministic naming scheme:

```
Generic function: max[T]
Specialization 1: max_Int
Specialization 2: max_Float64
Specialization 3: max_MyStruct

Generic struct: Stack[T]
Specialization 1: Stack_Int
Specialization 2: Stack_Float64
```

**Rule**: Replace type parameters with concrete type names, underscore-separated.

### Complex Type Parameters

```
max[List[Int]]:
  Name: max_List_Int

process[UnsafePointer[MyStruct]]:
  Name: process_UnsafePointer_MyStruct
```

### Nested Generics

```
Stack[Vector[Int]]:
  Name: Stack_Vector_Int

Matrix[List[List[Float]]]:
  Name: Matrix_List_List_Float
```

---

## Recursive Generics

### Type Expansion

Some generics recursively instantiate other generics:

```mojo
struct Optional[T]:
    has_value: Bool
    value: T

struct Box[T]:
    contents: Optional[T]

// Using Box[Optional[Int]]
box: Box[Optional[Int]]
```

#### Specialization Order

Generate specializations in dependency order:

1. `Optional_Int` — base specialization
2. `Box_Optional_Int` — depends on Optional_Int

**Tracking**: Build specialization dependency graph.

---

## Conditional Compilation

### Compile-Time Constraints

Generics may have compile-time constraints that eliminate specializations:

```mojo
fn to_string[T where conforms_to(T, Stringifiable)](value: T) -> String:
    return value.to_string()

// Legal: Int conforms to Stringifiable
s1 = to_string[Int](42)

// Illegal: Union doesn't conform
s2 = to_string[Union[Int, Float]](...)  # Compile error
```

**In GIMPLE**: Record compile-time decisions; only generate specializations for valid types.

---

## Limitations and Future Work

### Current Implementation

1. **No specialization**: All generics erased to base type
2. **No constraint checking**: Impossible to verify `where` clauses
3. **No monomorphization**: No generated specialized code
4. **No nested generics**: Recursive type parameters not fully supported

### Future: Full Generics

1. **Automatic specialization detection**: Scan code for all type instantiations
2. **Lazy specialization**: Generate specializations only as needed
3. **Specialization caching**: Reuse generated code across modules
4. **Constraint resolution**: Check trait conformance at specialization time
5. **Partial specialization**: Allow generic specialization of generic code
   ```mojo
   fn process[T, U](a: T, b: U) -> T:
       # Generic in two parameters
   
   fn process_int[U](a: Int, b: U) -> Int:
       # Partial specialization: T = Int, U generic
   ```

---

## Integration with GIMPLE Codegen

### Specialization Collection

During first pass of module codegen, collect generic instantiations:

```python
def _collect_generic_specs(self, stmts):
    """Scan all statements for generic instantiations."""
    for stmt in stmts:
        # Recursively scan for CallExpr, VarDecl, etc.
        # When CallExpr with generic function found:
        #   (func_name, type_args) → record in generic_specs
```

### Specialization Generation

After main codegen, generate specialized versions:

```python
def _generate_specializations(self):
    """Generate code for each recorded generic specialization."""
    for (func_name, type_args) in self.generic_specs:
        spec_name = self._specialize_name(func_name, type_args)
        # Re-run codegen with type parameters bound to type_args
        # Emit specialized function with spec_name
```

### Type Resolution with Generics

When resolving types in specialized code, substitute type parameters:

```python
# During specialization of max[Int]
# Binding: T → Int

def _resolve_type(self, ann):
    if ann == 'T':
        return self.type_bindings.get('T', 'int')  # Substitute
    # ... normal resolution
```

---

## Example: Generic Stack Implementation

### Mojo Source

```mojo
struct Stack[T]:
    data: List[T]
    
    fn new() -> Stack[T]:
        return Stack[T](data=[])
    
    fn push(self, value: T):
        self.data.append(value)
    
    fn pop(self) -> T:
        return self.data[-1]

// Usage
int_stack: Stack[Int] = Stack[Int].new()
int_stack.push(42)
value = int_stack.pop()
```

### Generated C (Monomorphized)

```c
typedef struct {
    MojoList *data;
} Stack_Int;

Stack_Int __GIMPLE Stack_Int_new (void)
{
  Stack_Int _result;
bb_2:
  _result.data = mojo_list_new();
  return _result;
}

void __GIMPLE Stack_Int_push (Stack_Int *self, int value)
{
bb_2:
  mojo_list_append_int(self->data, value);
  return;
}

int __GIMPLE Stack_Int_pop (Stack_Int *self)
{
  int _result;
  int64_t _idx;
bb_2:
  _idx = mojo_list_len(self->data) - 1;
  _result = (int)mojo_list_get_int(self->data, _idx);
  return _result;
}

// Main code
int main (void)
{
  Stack_Int _int_stack;
  int _value;
bb_2:
  _int_stack = Stack_Int_new();
  Stack_Int_push(&_int_stack, 42);
  _value = Stack_Int_pop(&_int_stack);
  printf("%d\n", _value);
  return 0;
}
```

---

**Specification Date**: 2026-04-28  
**Status**: Generics specification for monomorphization strategy (implementation deferred)  
**Integration**: Future integration with gimple_codegen.py for specialization generation
