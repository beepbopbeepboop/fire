# Mojo Parser Tools

Tools for analyzing and debugging the Mojo stdlib parser.

## Files

### analyze_stdlib_errors.py
Analyzes the Mojo stdlib compilation and groups any parsing errors by type.

**Usage:**
```bash
python tools/analyze_stdlib_errors.py
```

**Output:**
- Lists total passing/failing modules
- Groups errors by type
- Shows frequency of each error
- Lists which files have each error type

This tool is useful for:
- Identifying high-impact parsing issues to fix
- Tracking progress on parser improvements
- Finding patterns in parsing failures

## Parser Improvements

The Mojo parser has been improved to handle:
- Return statement tuples: `return a, b, c`
- Postfix move operator with member access: `expr^.method()`
- Comptime function type definitions
- Keywords as function names: `def read()`, `def write()`
- Tuple assignments: `a, b = x, y`
- Annotated assignments: `target: Type = value`
- Function types in type annotations: `func: def() -> ReturnType`

## Current Status

- **Passing:** 230/277 modules (83%)
- **Failing:** 47 modules

See `STDLIB_PARSING_ISSUES.md` for detailed analysis of remaining issues.

## Remaining Issues

The main remaining parsing challenges are:

1. **Complex subscript syntax** (6 files)
   - Keyword arguments with slices: `x[byte=1:]`
   - Mixed keyword/positional arguments

2. **Member access with newlines** (3 files)
   - Incomplete member access at line end

3. **Unusual comma patterns** (3 files)
   - Context-dependent comma parsing

4. **Other edge cases** (35+ files)
   - Various advanced Mojo syntax patterns

See `STDLIB_PARSING_ISSUES.md` for complete documentation with test cases.
