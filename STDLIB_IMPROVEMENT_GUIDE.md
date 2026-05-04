# Stdlib Compilation Improvement Guide

## Current Status
- **Pass Rate:** 107/277 files (38.6%)
- **Test Coverage:** 142 tests passing, 0 regressions
- **Architecture:** Generator-based improvements (compiler_gen.py)

## How to Make Future Improvements

All improvements should be made through the **generator** (`compiler_gen.py`), NOT directly to the generated `mojo_compiler.py` file.

### Workflow
1. Identify the syntax pattern causing failures
2. Modify the appropriate generator method in `compiler_gen.py`
3. Run `python run.py` to regenerate `mojo_compiler.py`
4. Test with `python compile_stdlib.py`
5. Verify tests still pass with `make check-gimple`

## Remaining Blockers (Top Issues)

### 1. Complex Bracket Expressions (10 files)
**Error:** `Unexpected RBRACKET`  
**Cause:** Nested or complex type expressions with multiple bracket levels  
**Example:** `Dict[K, V][...complex...]`  
**Solution:** Enhance `_parse_type_ann()` in generator to handle:
- Multi-level nested brackets
- Complex generic constraints
- Variadic parameters

**Generator Location:** `compiler_gen.py`, lines 1260-1310

### 2. Multi-line Expressions (8 files)
**Error:** `Unexpected NEWLINE`  
**Cause:** NEWLINE tokens appearing inside expressions that should suppress them  
**Example:**
```mojo
result = function(
    arg1,
    arg2
)
```
**Solution:** The tokenizer tracks `paren_depth` but may need enhancement for:
- Complex multi-line type annotations
- Continuation across multiple bracket levels

**Generator Location:** Lines tracking paren_depth in tokenizer generation

### 3. Generic Constraint Syntax (6 files)
**Error:** `Unexpected COMMA` or `Expected COLON got COMMA`  
**Cause:** Complex trait bounds and generic constraints with multiple parameters  
**Example:** `struct Wrapper[T: Trait1 & Trait2, U: OtherTrait]`  
**Solution:** Enhance parameter parsing to handle:
- Trait intersection with `&`
- Multiple trait bounds
- Complex constraint expressions

**Generator Location:** `_gen_parse_funcdef()` around line 1410

### 4. Backtick Type Edge Cases (Multiple Files)
**Error:** Interactions between backtick types and other syntax  
**Cause:** Backticks in docstrings vs. actual type annotations  
**Solution:** Add context-aware backtick handling in:
- Type annotation parser
- Member access expressions
- String concatenation boundaries

**Generator Location:** `_parse_type_ann()` and member access generation

## High-Impact Improvements (Estimated ROI)

| Issue | Files | Complexity | Effort | Expected Impact |
|-------|-------|-----------|--------|-----------------|
| Generic constraints with `&` | 6-8 | Medium | 2-3 hours | +2-3% pass rate |
| Multi-line bracket handling | 5-8 | Medium | 2-3 hours | +2-3% pass rate |
| Trait bounds in parameters | 5+ | Medium | 1-2 hours | +2% pass rate |
| MLIR attribute syntax | 10+ | High | 4-6 hours | +3-4% pass rate |
| Context managers | 3-5 | Medium | 1-2 hours | +1-2% pass rate |

## Code Generation Patterns to Understand

### String Building in Generator
Most generator methods build code as lists of strings:
```python
L = [
    '    def _parse_thing(self):',
    '        self._advance()',
    '        return result',
]
```

This list is joined with `'\n'.join(L)` at the end.

### Common Token Checks
```python
# In generator code (becomes part of generated parser):
'        if self._peek().kind == "NAME" and self._peek(1).kind == "ASSIGN":'
'            self._advance()  # skip name'
'            self._advance()  # skip ='
```

### Lookahead Pattern
The parser has `_peek(n)` to look ahead `n` tokens (default 1 token).

## Testing Methodology

### Quick Test
```bash
cat > /tmp/test.mojo << 'EOF'
# Your test code
EOF
cat /tmp/test.mojo | python mojo_compiler.py
```

### Full Test Suite
```bash
make check-gimple           # Unit tests (142 tests)
python compile_stdlib.py    # Stdlib files
```

### Targeted Module Testing
```bash
python compile_stdlib.py --module builtin   # Just builtin module
```

## Debugging Tips

### Find First Failing Line
```python
# Binary search in Python
for n in range(start, end):
    code = ''.join(lines[:n])
    result = subprocess.run(['python', 'mojo_compiler.py'], input=code, ...)
    if result.returncode != 0:
        print(f"Error at line {n}")
        break
```

### Extract Error Context
```python
match = re.search(r'SyntaxError: (.+)', stderr)
if match:
    error_msg = match.group(1)
```

## Key Generator Methods

| Method | Purpose | Lines |
|--------|---------|-------|
| `_gen_parse_for()` | For loop parsing | 1356-1370 |
| `_gen_parse_funcdef()` | Function definition parsing | 1378-1468 |
| `_parse_type_ann()` generation | Type annotation parsing | 1260-1310 |
| `_parse_postfix()` generation | Member access, subscripts, calls | 1040-1120 |
| `_parse_primary()` generation | Literals, identifiers, parenthesized expressions | 1118-1180 |

## Architecture Insights

1. **Spec-driven generation:** The .md specification files are parsed, and the generator creates a compiler from the extracted definitions.

2. **Token types:** STRING, NAME, KW, INT, FLOAT, OP, LPAREN, RPAREN, LBRACKET, RBRACKET, LBRACE, RBRACE, COLON, COMMA, DOT, ASSIGN, NEWLINE, INDENT, DEDENT, EOF

3. **Conventions:** Function parameter conventions (`var`, `mut`, `ref`, `out`, `read`, `deinit`) are tracked separately in `param_convs` dict.

4. **Type annotations:** Returned as strings, not AST nodes, since they're not fully evaluated.

## Known Limitations

1. **Incomplete semantic analysis:** Parser validates syntax but not type semantics
2. **Simplified operator precedence:** Handles basic cases, complex precedence may need tuning
3. **GPU support:** Stubbed out, full GPU codegen is marked as deferred
4. **Python extension API:** `PythonModuleBuilder` not implemented
5. **Advanced generics:** Complex constraint expressions not fully supported

## Next Priority Items

If continuing work, prioritize in this order:
1. Generic constraints with trait intersection (`&`)
2. Multi-line bracket expression improvements
3. Trait bounds parameter parsing
4. MLIR attribute syntax enhancements
5. Implicit conversions and context managers

This would bring pass rate to ~45-50% with reasonable effort.
