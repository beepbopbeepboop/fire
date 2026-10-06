# Codegen.mojo - Stubbed Dependencies Analysis

## What's Stubbed

Codegen.mojo has 3 categories of stubbed/undefined dependencies:

### 1. **generated_dispatch** Module (TYPE TABLES & DISPATCH)

**What it provides:**
```python
_SIGNED = {'int8_t': 1, 'int16_t': 2, 'int32_t': 3, 'int': 3, 'int64_t': 4}
_UNSIGNED = {'uint8_t': 1, 'uint16_t': 2, 'uint32_t': 3, 'unsigned int': 3, 'uint64_t': 4}
_FLOAT = {'__fp16': 1, 'float': 2, 'double': 3}

_BIN_OPS = {'+': '+', '-': '-', '*': '*', '/': '/', '%': '%', ...}  # Operator mapping
_CMP_OPS = ['==', '!=', '<', '<=', '>', '>=', 'in', 'is', 'and', 'or']  # Comparison operators

_STMT_DISPATCH = {
    'PassStmt': '_gen_stmt_PassStmt',
    'AssignStmt': '_gen_stmt_AssignStmt',
    'IfStmt': '_gen_stmt_IfStmt',
    # ... maps AST statement type → handler method name
}

_EXPR_DISPATCH = {
    'IntLiteral': '_lower_IntLiteral',
    'BinaryOp': '_lower_binary',
    'CallExpr': '_lower_call',
    # ... maps AST expression type → handler method name
}
```

**Where used in codegen.mojo:**
- Line 52-54: `TypeLattice` class uses `_SIGNED`, `_UNSIGNED`, `_FLOAT`
- Line 438-439: `_BIN_OPS`, `_CMP_OPS` for operator lowering
- Line 750: `_EXPR_DISPATCH.get()` to dispatch expression code generation
- Line 1680: `_STMT_DISPATCH.get()` to dispatch statement code generation

**Impact:** CRITICAL - These dispatch tables are essential for codegen to work. Without them, codegen can't route AST nodes to their handlers.

### 2. **module_loader** Module (STDLIB IMPORTS)

**What it provides:**
```python
class ModuleLoader:
    def load_module(module_name: str) -> parsed_AST
    def get_symbol_type(module: str, symbol: str) -> type_info
    
def load_module(module_name) -> Module
def get_symbol_type(module, symbol) -> type_info
```

**Where used in codegen.mojo:**
- Line 31: Commented as stubbed
- Line 2603: `load_module(s.module)` in import handling

**Impact:** MEDIUM - Only used when codegen processes `ImportStmt` nodes. Can work with simple stubs that return empty modules.

### 3. **Implicit Dependencies (from comments)**

The comment on lines 16-30 says:
```python
# Imported from mojo_compiler:
from_mojo_compiler = (
    IntLiteral, FloatLiteral, ..., tokenize, Parser,
)
```

But these aren't actually imported - they're just documented. The code expects them to be available in scope.

**What's needed:**
- `Parser` class (from parser.mojo) ✓ Available
- `tokenize` function (from tokenizer.mojo) ✓ Available
- AST node classes (from ast_nodes.mojo) ✓ Available

## Summary Table

| Dependency | Module | What | Impact | Status |
|---|---|---|---|---|
| `_SIGNED`, `_UNSIGNED`, `_FLOAT` | generated_dispatch | Type rank tables | CRITICAL - type promotion | Stubbed |
| `_BIN_OPS`, `_CMP_OPS` | generated_dispatch | Operator maps | CRITICAL - operator lowering | Stubbed |
| `_STMT_DISPATCH` | generated_dispatch | Statement dispatch | CRITICAL - routing | Stubbed |
| `_EXPR_DISPATCH` | generated_dispatch | Expression dispatch | CRITICAL - routing | Stubbed |
| `load_module` | module_loader | Load imported modules | MEDIUM - imports only | Stubbed |
| `get_symbol_type` | module_loader | Get symbol types | MEDIUM - type checking | Stubbed |
| `Parser` | parser.mojo | Parse Mojo code | Available ✓ | Not needed (we parse beforehand) |
| `tokenize` | tokenizer.mojo | Tokenize code | Available ✓ | Not needed (we tokenize beforehand) |

## Can Codegen Work Without These?

**Short answer: Partially, yes.**

The codegen.py in Python has all these defined. When we transpiled to codegen.mojo, these weren't properly included. 

**To make codegen fully functional:**

Option 1: Fix the stubs
- Copy dispatch tables from generated_dispatch.py into codegen.mojo (or properly import)
- Add basic module_loader stubs
- This would make full codegen work

Option 2: Provide minimal stubs
- For bootstrap purposes, we could provide minimal implementations:
  - Return basic dispatch for common AST types
  - Return empty module for imports
  - Still produces C code, just with limitations

Option 3: Skip codegen for now
- Use interpreter for tokenize + parse
- Output AST as final result (sufficient for bootstrap verification)
- Complete full codegen later

## Recommendation

**For immediate bootstrap goal:** Option 2 (minimal stubs)
- We need just enough codegen to output *something*
- Full correctness can come later
- Allows proof-of-concept Mojo self-hosting

This requires:
1. Adding dispatch table stubs to codegen.mojo (10-15 lines)
2. Adding minimal module_loader stub (5-10 lines)
3. Testing that GimpleGen class initializes and has basic methods available
4. Can then test `compile_to_gimple()` function
