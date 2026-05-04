# GNU Extensions and Implementation Details

This document consolidates extensions to the Mojo language specification and implementation details specific to this compiler reference implementation. Content is organized by feature area.

---

## Module System Implementation

### Overview

The Mojo module system enables code organization and reuse. Official documentation: https://docs.modular.com/mojo/manual/packages/

From official docs:
- **Module**: A single `.mojo` source file that can be imported
- **Package**: A directory containing a `__init__.mojo` file
- **Package compilation**: `mojo package mypackage -o mypack.mojopkg`

### Module Resolution (Implementation-Specific)

Our compiler resolves module paths as follows:

```
std.math        → stdlib/std/math/__init__.mojo or stdlib/std/math.mojo
std.memory      → stdlib/std/memory/__init__.mojo or stdlib/std/memory.mojo
mymodule        → ./mymodule.mojo or ./mymodule/__init__.mojo
mypackage.mod   → ./mypackage/mod.mojo or ./mypackage/mod/__init__.mojo
```

**Resolution Order**:
1. Relative to current file directory
2. Relative to module search path (e.g., MOJO_PATH environment variable)
3. Relative to stdlib directory

### Symbol Extraction (Implementation-Specific)

The module_loader.py component extracts exported symbols by parsing function/struct definitions:

```mojo
# Extracted symbols and their types:
fn function_name(params) -> ReturnType:    # Type: ReturnType, Params: [(name, type), ...]
struct StructName:                          # Type: StructName *, Params: N/A
def _private_fn():                          # Not exported (starts with _)
```

**Type Inference**:
- Function return types: explicitly annotated (e.g., `-> Int`, `-> Double`, `-> Bool`)
- Function parameters: extracted from signature (e.g., `(x: Int, y: Int64) -> Int`)
  - Parameter names and types parsed from function definition
  - Default parameter values preserved in metadata
  - Argument conventions (`read`, `mut`, `var`, `ref`, `out`) extracted but lowered to simple types in C
- Struct/class names: resolve to pointer types (heap allocation model)
- Type mapping (Mojo → C):
  - `Int` → `int`
  - `Int8`, `Int16`, `Int32`, `Int64` → `int8_t`, `int16_t`, `int32_t`, `int64_t`
  - `Float32`, `Float64` → `float`, `double`
  - `Bool` → `_Bool`
  - `String` → `char *` (const char * for parameters)
  - `MojoList` → `MojoList *`
  - `MojoDict` → `MojoDict *`
  - User structs → `StructName *`
- Default: `int` (unknown type) if inference fails

**Example Symbol Extraction**:
```mojo
# Input .mojo file (std.math.mojo)
fn sqrt(x: Float64) -> Float64:
    ...

fn pow(x: Float64, n: Float64) -> Float64:
    ...

fn clamp(val: Int, min_val: Int, max_val: Int) -> Int:
    ...
```

Extracted symbols:
```python
{
  'sqrt': {
    'return_type': 'double',
    'parameters': [('x', 'double')],
    'signature': 'double sqrt (double x)'
  },
  'pow': {
    'return_type': 'double',
    'parameters': [('x', 'double'), ('n', 'double')],
    'signature': 'double pow (double x, double n)'
  },
  'clamp': {
    'return_type': 'int',
    'parameters': [('val', 'int'), ('min_val', 'int'), ('max_val', 'int')],
    'signature': 'int clamp (int val, int min_val, int max_val)'
  }
}
```

### Code Generation: C Backend (GIMPLE)

Imports lower to C extern declarations in the preamble, including parameter information:

#### Before (Current Implementation):

```mojo
# Input: Mojo code
from std.math import sqrt, pow

def main() -> Int:
    var x: Int = sqrt(9)
    return x
```

Current generation (no parameters):
```c
extern int sqrt (void);  /* from std.math */
extern int pow (void);   /* from std.math */

int main (void) {
  int x;
  x = sqrt ();  /* ← ERROR: missing argument */
  return x;
}
```

#### After (Enhanced with Parameters):

With parameter type extraction, generates correct signatures:

```c
extern double sqrt (double x);  /* from std.math */
extern double pow (double x, double n);  /* from std.math */

int main (void) {
  double _t1;
  int x;
  _t1 = sqrt (9.0);  /* ← Correct: argument passed */
  x = (int) _t1;
  return x;
}
```

**Implementation Details**:

1. **Symbol Type Extraction**: module_loader.py extracts function parameters as list of `(name, type)` tuples
2. **Signature Generation**: gimple_codegen.py uses extracted parameters to build full C signature
3. **Type Coercion**: Argument types coerced to parameter types via `TypeLattice.join` if needed
4. **Extern Declaration**: Generated as `extern RetType symbol_name (ParamType1 name1, ParamType2 name2, ...);`

**Type Mapping for Extern Declarations**:
- Mojo parameter types map to C types (see Type Inference section above)
- Parameter names preserved in extern declarations (for readability; not required by C)
- `const` qualifier added for `read` convention on pointer parameters

**Example: Full Parameter Extraction and Codegen**:

Input module (std.memory.mojo):
```mojo
fn allocate(size: Int64) -> UnsafePointer[Int]:
    ...

fn free(ptr: UnsafePointer[Int]) -> Bool:
    ...
```

Module loader extracts:
```python
'allocate': {'return_type': 'int64_t *', 'parameters': [('size', 'int64_t')], ...}
'free': {'return_type': '_Bool', 'parameters': [('ptr', 'int64_t *')], ...}
```

GIMPLE codegen generates:
```c
extern int64_t * allocate (int64_t size);  /* from std.memory */
extern _Bool free (int64_t * ptr);  /* from std.memory */
```

Usage in code:
```mojo
from std.memory import allocate, free

def main() -> Int:
    var ptr: UnsafePointer[Int] = allocate(100)
    var result: Bool = free(ptr)
    return 0
```

Generates:
```c
int64_t * _t1;
_Bool _t2;
int _t3;

_t1 = allocate (100);
ptr = _t1;
_t2 = free (_t1);
result = _t2;
_t3 = 0;
return _t3;
```

**Limitations & TODOs** (remaining):
- Parameter information extraction now fully specified (TODO item for module_loader.py)
- Struct method calls on imported types still not supported (need struct method metadata)
- Generic type parameters not yet specified (need generic instantiation rules)
- Private/public distinction not enforced (need AST-based visibility checking)
- Module initialization code not implemented (need top-level statement execution)
  
- Struct method calls: cannot call methods on imported struct types
  - Imported structs are opaque types
  - Need: Struct method mangling rules in module loader
  
- Generic types: no support for generic imports
  - Need: Generic parameter instantiation rules
  
- Private symbols: no enforcement of private/public distinction
  - Need: AST-based visibility checking
  
- Module initialization: not implemented
  - Module-level statements don't execute on import
  - Need: Track and execute top-level code

---

## GIMPLE Code Generation Specification

### Overview

GIMPLE (Gimplified Intermediate Representation) is GCC's IR format with structured control flow. Our compiler lowers Mojo AST to C code annotated with `__GIMPLE` for gcc-mp-15 (`-fgimple`).

### General Principles

1. **Temp variables**: All subexpression results assigned to temps (`_tN`) at function entry
2. **Block labels**: Entry block is `bb_2`; basic blocks numbered sequentially starting at 3
3. **No in-line casts**: Casts in function arguments, comparisons, or return statements must be split into assignments
4. **Type promotion**: Binary operations promote operands to common type via `TypeLattice.join` before emission
5. **GIMPLE constraints**: 
   - Comparison results must be `_Bool`, not `int`
   - `!` operator not valid (use `x == 0` instead)
   - `sizeof(TYPE)` only valid when TYPE appears in function signature
   - Cast-of-call-result forbidden: must split into temp assignment then cast

### Operators

#### Binary Arithmetic: `+ - * / % ** //`

**Lowering rules**:
- Both operands promoted to common type via `TypeLattice.join`
- `**` with float: `pow()`; with int: `(int) pow((double) a, (double) b)`
- `//` floor division: `__mojo_floordiv(a, b)` for int; `__builtin_floor(a/b)` for float
- Result assigned to temp: `_tN = a op b;`

#### Comparison: `== != < <= > >=`

**Lowering rules**:
- Both operands promoted to common type
- Result is `_Bool` (not `int`)
- Comparison chaining: `a < b < c` → `(a < b) && (b < c)` with intermediate temps
- `is` operator: `(void *) a == (void *) b` (pointer identity for refs; value compare for scalars)
- `is not`: negated form

#### Logical: `and or`

**Lowering rules**:
- `a and b` → `a && b` (short-circuits)
- `a or b` → `a || b` (short-circuits)
- Operands must be `_Bool`
- Result is `_Bool`

#### Bitwise: `& | ^ << >>`

**Lowering rules**:
- Operands promoted to common integer type
- Operator syntax unchanged
- Result assigned to temp

#### Matrix Multiply: `@`

**Lowering**:
- Calls struct `__matmul__` method: `StructName___matmul__(left, right)`
- Struct name determined from left operand type
- Method name mangled (double underscore prefix and suffix)
- Returns result of method call

Example:
```mojo
var result: Matrix = a @ b
```

Generates:
```c
Matrix * _t1 = Matrix___matmul__ (a, b);
result = _t1;
```

**Performance**: Current implementation delegates to method calls. High-performance version (TODO) would use BLAS (dgemm) or SIMD intrinsics.

#### Augmented Assignment: `+= -= *= /= //= %= **= @= &= |= ^= <<= >>=`

**Lowering rules**:
- `x += expr` → `x = _coerce(x, expr_type) op expr`
- Type of result determined by `TypeLattice.join(x_type, expr_type)`
- Creates intermediate variable if type changes

#### Unary: `- + ~ not`

**Lowering rules**:
- Single operand lowered to temp
- `- x` → `-x`
- `+ x` → `+x`
- `~ x` → `~x`
- `not x` → `x == 0` (requires cast to int first if `_Bool`)

### Expressions

#### Literals

- Numeric: `42` → `42`, `3.14` → `3.14`, `0xFF` → `0xFF`
- String: `"hello"` → `"hello"` (const char *)
- Boolean: `True` → `1`, `False` → `0` (both `_Bool`)

#### Collections

**Lists**: `[a, b, c]`
```c
MojoList * _t1 = mojo_list_new();
mojo_list_append_int(_t1, a);
...
```

**Dicts**: `{k: v, ...}`
```c
MojoDict * _t1 = mojo_dict_new();
mojo_dict_set_int(_t1, k, v);
...
```

**Sets**: `{a, b, c}`
```c
MojoSet * _t1 = mojo_set_new();
mojo_set_add_int(_t1, a);
...
```

#### Subscript Access: `x[i]`

**Lowering varies by type**:
- Plain pointers: `*(_mojo_at_T(p, i))` (pointer arithmetic forbidden in GIMPLE)
- MojoList: `mojo_list_get_int/double/str(list, i)`
- MojoStr: `mojo_str_char_at(str, i)`
- MojoDict: `mojo_dict_get_int/double/str(dict, key)`

#### Member Access: `obj.field`

**Lowering**:
- Struct types: `obj->field` or `obj.field` depending on pointer-ness
- Type lookup via `struct_field_types` dict
- Result assigned to temp if used in larger expression

#### Function Calls: `f(args)`

**Lowering**:
- Arguments lowered to temps
- Return type determined from symbol table
- Result assigned to temp: `_tN = f(arg1, arg2, ...);`
- Cast-of-call-result forbidden: must split

#### Ternary Expression: `x if cond else y`

**Lowering**:
```c
_Bool _t1 = (cond evaluated);
result_type _t2 = _t1 ? x : y;
```

#### Walrus Expression: `(x := expr)`

**Lowering**:
- Right-hand side lowered to temp
- Assigned to target variable
- Expression evaluates to assigned value
- Complex LHS: struct field via `->` or `.`; array element via `mojo_list_set_*`

### Statements

#### Variable Declaration: `var x: T = expr`

**Lowering**:
- Variable declared at function entry (GIMPLE requirement)
- All declarations hoisted before first `bb_2:` label
- Initialization emitted as assignment

#### Assignment: `x = expr`

**Lowering**:
- Right-hand side lowered to temp
- If types differ, intermediate temp for cast
- Assignment emitted: `x = temp;` or `x = (type) temp;`

#### If Statement: `if cond: ... elif ... else: ...`

**Lowering**:
- Condition lowered to `_Bool` temp
- Each branch compiled to basic block
- Control flow via `goto` at end of blocks

#### While Loop: `while cond: ...`

**Lowering**:
- Condition lowered to temp at loop entry
- Loop body in basic block
- Continue jumps to condition re-check
- Break jumps to after loop

#### For Loop: `for i in range(...): ...`

**Lowering (fixed range)**:
- If `range(n)` has literal n: unroll or simple while
- If `range(a, b, step)` all literal: compute iterations
- Loop variable assigned each iteration

**Lowering (collection)**:
- For lists, dicts, sets, strings: use iterator protocol
- Create iterator via `__iter__` method
- Loop while `__has_next__` returns true
- Advance via `__next__` method

#### Return Statement: `return expr`

**Lowering**:
- Expression lowered to temp
- If declared return type differs, cast via intermediate
- `return temp;` emitted
- `main()` with no explicit return implicitly returns `0`

#### Try/Except: `try: ... except ExcType as name: ...`

**Lowering**:
- Exception frame pushed via `mojo_try_push()`
- Try block executed
- Exception caught via `setjmp`; handler block runs
- Exception name bound to `mojo_exc_msg_get()`

#### Raise Statement: `raise "message"`

**Lowering**:
- Message string passed to `mojo_exc_msg_set(msg)`
- `mojo_raise()` called unconditionally
- Bare `raise` (rethrow): just `mojo_raise()`

#### Comprehensions: `[expr for x in iterable]`

**Lowering**:
- Create result collection via `mojo_list_new()` / `mojo_set_new()` / `mojo_dict_new()`
- Iterate via iterator protocol
- For each iteration, evaluate expression and append/insert result
- Return result collection

### Type Resolution

#### TypeLattice (C11 Usual Arithmetic Conversion Rules)

Determines result type for binary operations:

```
int + int64_t       → int64_t
float + int         → float
int + double        → double
_Bool + int         → int (bool promotes first)
```

**Rules**:
1. `_Bool` promotes to `int` first
2. Float > Int (float wins)
3. Wider numeric type wins
4. Mixed signed/unsigned: unsigned wins if rank >= signed rank

#### Struct Types

- User-defined struct names resolve to `StructName *` (heap allocated)
- Constructor calls via `_alloc_StructName()` helper
- Method calls mangled: `StructName_methodname(self, ...)`
- Field access via `->` or `.` based on pointer-ness

### Preamble Helpers

#### Type Promotion
- `_coerce(value, target_type)` for implicit casts

#### Container Operations
- `mojo_list_new()` / `mojo_list_append_*()` / `mojo_list_get_*()` / `mojo_list_len()`
- `mojo_dict_new()` / `mojo_dict_set_*()` / `mojo_dict_get_*()` / `mojo_dict_contains()`
- `mojo_set_new()` / `mojo_set_add_*()` / `mojo_set_contains_*()` / `mojo_set_len()`
- `mojo_str_len()` / `mojo_str_char_at()` / `mojo_str_slice()` / `mojo_str_eq()`

#### Pointer Helpers
- `_mojo_at_T(ptr, offset)` for safe pointer arithmetic (returns `ptr + offset`)
- `_alloc_StructName()` for struct allocation

#### Exception Handling
- `mojo_try_push()` / `mojo_exc_pop()` / `mojo_raise()` / `mojo_exc_msg_set()` / `mojo_exc_msg_get()`

### Known Limitations & TODOs

#### Current Issues
- No complex function signatures (parameters passed via `(void)`)
- No generic type instantiation
- No async/await lowering
- Matrix multiply delegates to method calls (not optimized)

#### Future Enhancements (Deferred)
- SSA form output: `__GIMPLE (ssa)` with `__BB(N)` and `__PHI` nodes
- GPU kernel launch: CUDA/HIP codegen
- Python interop: CPython embedding
- Custom iterators: iterator protocol for user types beyond standard protocol

---

## Code Generation Pipeline

### Current Architecture

```
Mojo source (.mojo)
    ↓
Lexer/Tokenizer (tokenize())
    ↓
Parser (Parser class, recursive descent)
    ↓
AST nodes (mojo_compiler.py, generated)
    ↓
GIMPLE Codegen (gimple_codegen.py, hand-written)
    ↓
C code with __GIMPLE annotations
    ↓
gcc-mp-15 -fgimple
    ↓
Object file / Executable
```

### Components (Implementation-Specific)

**mojo_compiler.py** (GENERATED from .md specs):
- Lexer: tokenization
- Parser: recursive descent AST generation
- AST node definitions

**gimple_codegen.py** (HAND-WRITTEN, should be generated):
- Converts AST to C with GIMPLE annotations
- Type inference and promotion
- Basic block generation
- 2900+ lines of lowering rules

**module_loader.py** (HAND-WRITTEN, should be generated):
- Resolves module paths
- Parses .mojo files
- Extracts function signatures and types
- Caches loaded modules

**test_*.py** (Test infrastructure):
- test_gimple.py: 142 codegen tests
- test_gimple_runner.py: 7 execution tests
- test_imports.py: module import verification
- test_import_integration.py: end-to-end integration tests

### Future: Code Generation from Specs

**TODO items** (see PLAN.md):

1. **Generate module_loader.py** from mojo-modules.md (upstream) + extensions
   - Create module_spec_gen.py
   - Extract path resolution rules
   - Generate symbol extraction logic

2. **Generate gimple_codegen.py** from operator/statement/expression specs
   - Create gimple_spec_gen.py
   - Generate operator dispatch tables
   - Generate lowering methods
   - Generate type promotion rules

3. **Create missing specification files**:
   - gimple-runtime.md (container/exception APIs)
   - gimple-type-system.md (type lattice rules)
   - gimple-exceptions.md (try/except lowering)
   - gimple-closures.md (closure lifting)
   - gimple-iterators.md (iterator protocol)
   - gimple-generics.md (generic instantiation)
   - gimple-memory.md (pointer operations)
   - mojo-type-system.md (type rules)
   - mojo-runtime-api.md (runtime functions)

---

## Integration with Official Mojo

### Upstream Documentation References

- **Modules and Packages**: https://docs.modular.com/mojo/manual/packages/
- **Operators**: https://docs.modular.com/mojo/reference/mojo-operators/
- **Simple Statements**: https://docs.modular.com/mojo/reference/mojo-simple-statements/
- **Expressions**: https://docs.modular.com/mojo/reference/mojo-expressions/
- **Compilation**: https://docs.modular.com/mojo/tools/compilation/
- **Compilation guide**: Source code shown in mojo-manual-language-basics.md

### Conflicts & Extensions

Our implementation extends the official specification in these areas:

1. **Module Loading**: Implementation adds module_loader.py for path resolution and symbol extraction
2. **GIMPLE Lowering**: Implementation defines how each construct lowers to C
3. **Type Lattice**: Implementation specifies C11 usual arithmetic conversions
4. **Runtime Helpers**: Implementation provides container/exception runtime API

### Documentation Strategy

- **Official** (.md files from upstream): Language syntax and semantics
- **This document** (GNU-EXTENSIONS.md): Implementation details, lowering rules, code generation
- **IMPL.md**: What features are implemented
- **PLAN.md**: What features are TODO and design decisions
- **CODEGENPLAN.md**: What TODOs remain in gimple_codegen.py

---

**Last Updated**: 2026-04-28  
**Status**: Comprehensive; consolidates module system, GIMPLE spec, and code generation architecture
