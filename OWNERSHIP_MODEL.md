# Ownership Model for stage2/mojo

## Current State

**Parser**: ✅ Correctly identifies `^` as postfix ownership transfer
- Line 1285-1293 in mojo_compiler.py
- Creates `UnaryOp(op="^", operand=expr)` for `x^`

**Codegen**: ❌ Currently ignores ownership semantics
- gimple_codegen.py has no special handling for `^` operator
- Line 858: `^` not in `{'-', '~', '+'}` operator map
- Ownership transfer is parsed but not enforced in C code

**Runtime**: ❌ No lifetime tracking
- No destructor calls
- No ASAP destruction
- Variables not marked as moved/uninitialized

---

## Mojo Ownership Rules (from manual-values.md)

1. **Single Owner**: Every value has exactly one owner at a time
2. **Lifetime Binding**: When owner's lifetime ends, value is destroyed
3. **Reference Extension**: References extend owner's lifetime
4. **ASAP Destruction**: Values destroyed immediately after last use, not at scope end
5. **Transfer via `^`**: `x^` transfers ownership, leaving `x` uninitialized

### Argument Conventions

| Keyword | Behavior | Ownership |
|---------|----------|-----------|
| `read` (default) | Immutable reference | Caller retains |
| `mut` | Mutable reference | Caller retains |
| `var` | Function parameter | **Function receives** |
| `^` sigil | Explicit transfer | **Callee receives** |

---

## What stage2/mojo Should Do

### Strategy: Minimal Ownership (for interpreter/REPL)

For a simple Mojo interpreter running at stage2, full ownership tracking is not practical. Instead:

1. **Parse `^` correctly** ✅
   - Already working in mojo_compiler.py

2. **Track moved variables** (optional)
   - Mark variables moved via `^` as "uninitialized"
   - Could report error if used after move
   - Not required for basic functionality

3. **Skip destructor calls** (pragmatic for interpreter)
   - Mojo stdlib types (String, List, Dict) manage their own cleanup
   - No explicit destructors needed in interpreter
   - Real compiled code would need this

4. **Don't enforce ASAP destruction**
   - Too complex for interpreter
   - Not observable in REPL context

### Strategy: Full Ownership (for compiled stage2/mojo)

If stage2/mojo were to compile to binaries (future):

1. **Lifetime analysis** (pre-pass)
   - Track when each variable is created/used/last_used
   - Identify scopes and ownership transfers

2. **Destructor insertion**
   - At last use of owned value: call destructor
   - For structs with `__del__`: generate call before freeing
   - For strings/lists: free heap memory

3. **Move prevention**
   - Track moved variables
   - Error if used after move

4. **Reference handling**
   - Distinguish `read`, `mut`, `var` parameters
   - Extend owner lifetime if references exist

---

## Implementation Sequence

### Phase 1: Accept and Skip (current)
- Parse `^` ✅
- Ignore during codegen (implicit)
- Works for REPL

### Phase 2: Track Moves (optional)
- Codegen marks variables as moved
- Report errors on use-after-move
- No destructor calls yet

### Phase 3: Destruct on Scope Exit (future)
- Insert destructor calls
- Handle ASAP destruction
- Proper lifetime semantics

### Phase 4: Full Ownership (compiled stage)
- Lifetime checker
- Reference tracking
- Full ASAP destruction

---

## Current Test Coverage

From CODEGENPLAN.md: 142/142 tests pass

Tests likely cover:
- ✅ Basic expressions with `^`
- ✅ Function calls with transferred values
- ✅ Variable scoping
- ❌ Move-after-use detection (not enforced)
- ❌ Destructor calls (not generated)

---

## Recommendation for stage2/mojo

**Accept current minimal strategy**:
1. Parser handles `^` ✅
2. Codegen passes through as no-op (variables never actually freed in REPL)
3. For REPL, this is acceptable—Python GC handles cleanup

**If implementing compiled output** (beyond REPL):
1. Add `moved` flag to variable tracking
2. Generate error on use-after-move
3. Insert destructor calls at last-use points
4. Handle references extending lifetimes

---

## Code Locations

- **Parser**: mojo_compiler.py:1285-1293
- **Codegen**: gimple_codegen.py:852 (_lower_UnaryOp)
- **Documentation**: mojo-manual-values.md

## Current Bug: Invalid C Code Generation

**Test**: `consume(msg^)`

**Generated C code** (line 32 in test_ownership.ci):
```c
_t1 = ^msg;  /* INVALID - bitwise XOR with no RHS */
```

**Should be**:
```c
_t1 = msg;   /* Transfer ownership, msg value is now consumed */
```

**Root cause**: gimple_codegen._lower_UnaryOp() doesn't recognize `^` as special
- Line 858 in gimple_codegen.py: `'^' not in {'−', '~', '+'}`
- Falls through to generic unary operator handling
- Generates invalid C: `_t1 = ^msg;`

**Fix**: Either:
1. **Remove the operator** (simplest): `_t1 = msg;`
2. **Track the move**: Set `msg = 0;` (uninitialized marker)
3. **No-op for interpreter**: Just ignore `^` since Python GC handles cleanup

---

## Next: Audit stage2/mojo

Confirmed findings:
- ✅ Parser creates UnaryOp(op="^", operand=expr)
- ❌ Codegen generates invalid C: `^msg` instead of `msg`
- ❌ No tracking of moved variables
- ❌ No error on use-after-move

Before auditing compiled output, this bug must be fixed.
