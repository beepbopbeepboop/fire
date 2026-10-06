# GIMPLE Exception Handling Specification

Specification for lowering Mojo try/except/finally statements to GIMPLE code with exception context stack management.

Source: Extracted from gimple_codegen.py try/except/finally statement lowering (lines 1966-2065) and exception API integration.

---

## Overview

Exception handling in GIMPLE uses a runtime exception context stack:

1. **Push context**: `mojo_try_push()` creates new exception scope, returns non-zero if exception pending
2. **Execute body**: Code in try block runs; if exception raised, jumps to handler
3. **Pop context**: `mojo_exc_pop()` removes exception scope
4. **Handle exception**: Exception handler receives exception message via `mojo_exc_msg_get()`
5. **Finally block**: Always executes regardless of exception (normal or exceptional path)

---

## Exception Context Stack Model

### Runtime State

```
Exception Stack (thread-local or process-global):
  [Context 0: msg="", pending=false]
  [Context 1: msg="", pending=false]
  [Context N: msg="Division by zero", pending=true]  ← current
```

### Context Operations

- **push**: Allocates new context, returns ID or status code
- **pop**: Deallocates and exits current context
- **raise**: Sets `pending=true` on current context, jumps to exception handler
- **message**: Get/set exception description string for current context

---

## Try/Except Statement Lowering

### Mojo Syntax

```mojo
try:
    # try body
    risky_operation()
except error:
    # handler: error is exception message string
    print(f"Error: {error}")
finally:
    # finally body (always runs)
    cleanup()
```

### GIMPLE Code Structure

**High-level flow**:
```
1. Push exception context
2. Branch to try block or exception handler (based on context status)
3. Execute try body
4. If no exception: pop context, execute else (if present), jump to after
5. If exception: pop context, execute handler, execute finally (if present), jump to after
6. Execute finally (if present) on normal path too
7. Jump to after
8. Continue after try/except/else/finally
```

### Generated Code

For a simple try/except:
```python
try:
    result = risky()
except err:
    print(err)
```

Generates GIMPLE:
```c
_exc_id = mojo_try_push();       // Push exception context
_cond = _exc_id != 0;            // Check if exception pending
if (_cond) goto L_handler;       // Jump if exception
else goto L_try;                 // else execute try body

L_try:
  // ... try body code ...
  int _result = risky();
  mojo_exc_pop();                // Pop context on success
  goto L_after;

L_handler:
  mojo_exc_pop();                // Pop context in handler
  char *_err = (char *)mojo_exc_msg_get();  // Extract exception message
  // ... handler body ...
  goto L_after;

L_after:
  // continue ...
```

### Multi-Handler Try/Except

For multiple handlers, they execute sequentially in a single handler block:

```python
try:
    op()
except err1:
    handle1()
except err2:
    handle2()
```

Generates:
```c
_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  op();
  mojo_exc_pop();
  goto L_after;

L_exc:
  mojo_exc_pop();
  char *_err = (char *)mojo_exc_msg_get();
  // Execute handler 1
  handle1();
  // Execute handler 2
  handle2();
  goto L_after;

L_after:
  // ...
```

**Note**: In actual Mojo, multiple handlers would match specific exception types. In this simplified GIMPLE backend, all handlers execute unconditionally (not spec'd in runtime API). Pattern supports future refinement to add exception type dispatch.

### Try/Except/Else Statement

For try/except/else (else executes when no exception):

```python
try:
    result = risky()
except err:
    handle()
else:
    success(result)
```

Generates:
```c
_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  int _result = risky();
  mojo_exc_pop();
  goto L_else;          // Jump to else on success

L_exc:
  mojo_exc_pop();
  char *_err = (char *)mojo_exc_msg_get();
  // ... handler ...
  goto L_after;

L_else:
  success(_result);     // Else block
  goto L_after;

L_after:
  // ...
```

---

## Finally Block Lowering

**Semantics**: Finally block must execute on all paths (normal completion, exception, explicit return, break, continue).

### Try/Except/Finally

```python
try:
    risky()
except err:
    handle()
finally:
    cleanup()
```

Generates (simplified):
```c
_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  risky();
  mojo_exc_pop();
  // Finally on normal path
  cleanup();
  goto L_after;

L_exc:
  mojo_exc_pop();
  char *_err = (char *)mojo_exc_msg_get();
  handle();
  // Finally on exception path
  cleanup();
  goto L_after;

L_after:
  // ...
```

### Try/Else/Finally

```python
try:
    result = risky()
except err:
    handle()
else:
    success(result)
finally:
    cleanup()
```

Generates:
```c
_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  int _result = risky();
  mojo_exc_pop();
  goto L_else;

L_exc:
  mojo_exc_pop();
  char *_err = (char *)mojo_exc_msg_get();
  handle();
  // Finally after exception
  cleanup();
  goto L_after;

L_else:
  success(_result);
  // Finally after normal path
  cleanup();
  goto L_after;

L_after:
  // ...
```

### Early Return from Try/Finally

```python
def foo():
    try:
        return result()
    finally:
        cleanup()
```

**Challenge**: Return statement in try body must still execute finally before exiting function.

**Solution** (simplified): Return statements in try bodies first write result to temporary, then jump to finally block:

```c
int __result;

_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  __result = result();  // Capture return value
  mojo_exc_pop();
  goto L_finally;       // Jump to finally instead of returning

L_exc:
  mojo_exc_pop();
  // ... handler ...
  goto L_finally;

L_finally:
  cleanup();            // Always execute
  return __result;      // Return after finally
```

---

## Raising Exceptions

### Explicit Raise

```python
if condition:
    raise "Error message"
```

Generates:
```c
if (condition) {
    mojo_exc_msg_set("Error message");  // Set exception message
    mojo_raise();                        // Raise (non-local jump to handler)
}
```

### Raise in Handler (Re-raise)

```python
try:
    risky()
except err:
    handle()
    raise  # Re-raise the exception
```

Generates:
```c
L_exc:
  mojo_exc_pop();
  char *_err = (char *)mojo_exc_msg_get();
  handle();
  mojo_raise();  // Re-raise: propagate to parent handler
  goto L_after;
```

---

## With Statement Exception Safety

The `with` statement (context manager protocol) uses try/except internally to ensure `__exit__` is called on both normal and exceptional paths.

### Mojo With Statement

```mojo
with open("file.txt") as f:
    data = f.read()
```

### GIMPLE Lowering with Exception Safety

```c
File *_f;
_f = open("file.txt");
if (File___enter__ in exports) { File___enter__(_f); }

_exc_id = mojo_try_push();
_cond = _exc_id != 0;
if (_cond) goto L_exc; else goto L_try;

L_try:
  char *_data = f_read(_f);
  mojo_exc_pop();
  goto L_exit_normal;

L_exc:
  mojo_exc_pop();
  goto L_exit_exc;

L_exit_normal:
  if (File___exit__ in exports) { File___exit__(_f); }
  goto L_after;

L_exit_exc:
  if (File___exit__ in exports) { File___exit__(_f); }
  mojo_raise();       // Re-raise after cleanup
  
L_after:
  // ...
```

**Key property**: `__exit__` runs on both normal and exceptional completion.

---

## Exception Message Handling

### Setting Exception Message

When raising an exception with a message:

```c
mojo_exc_msg_set("Division by zero");
mojo_raise();
```

### Capturing Exception Message in Handler

When entering exception handler, message is extracted:

```c
char *_err = (char *)mojo_exc_msg_get();
```

### Message Lifetime

- Message valid in handler after `mojo_exc_msg_get()`
- Message lifetime extends to `mojo_exc_pop()`
- Handler must copy message if needed beyond function scope

---

## Nested Try/Except

Nested try blocks push/pop multiple contexts:

```python
try:
    try:
        inner_risky()
    except inner_err:
        inner_handle()
except outer_err:
    outer_handle()
```

Generates:
```c
// Outer try
_exc_id_1 = mojo_try_push();     // Depth 1
_cond_1 = _exc_id_1 != 0;
if (_cond_1) goto L_outer_exc; else goto L_outer_try;

L_outer_try:
  // Inner try
  _exc_id_2 = mojo_try_push();   // Depth 2
  _cond_2 = _exc_id_2 != 0;
  if (_cond_2) goto L_inner_exc; else goto L_inner_try;

  L_inner_try:
    inner_risky();
    mojo_exc_pop();              // Pop inner context
    goto L_after_inner;

  L_inner_exc:
    mojo_exc_pop();              // Pop inner context
    char *_inner_err = (char *)mojo_exc_msg_get();
    inner_handle();
    goto L_after_inner;

  L_after_inner:
    mojo_exc_pop();              // Pop outer context on success
    goto L_after_outer;

L_outer_exc:
  mojo_exc_pop();                // Pop outer context on exception
  char *_outer_err = (char *)mojo_exc_msg_get();
  outer_handle();
  goto L_after_outer;

L_after_outer:
  // ...
```

---

## Implementation: Setjmp-Based or Stack Unwinding

The specification above describes the **abstract** semantics. Implementation may use:

### Approach 1: Setjmp-Based (Implicit in Code)

```c
jmp_buf _exc_buf[MAX_DEPTH];
int _exc_depth = 0;
char _exc_msg[1024];

int mojo_try_push() {
    if (setjmp(_exc_buf[_exc_depth]) == 0) {
        _exc_depth++;
        return 0;  // Normal return from setjmp
    } else {
        return 1;  // Exception pending
    }
}

void mojo_raise() {
    longjmp(_exc_buf[_exc_depth - 1], 1);  // Jump to handler
}

void mojo_exc_pop() {
    _exc_depth--;
}

void mojo_exc_msg_set(const char *msg) {
    strncpy(_exc_msg, msg, sizeof(_exc_msg) - 1);
}

char *mojo_exc_msg_get() {
    return _exc_msg;
}
```

### Approach 2: Stack Unwinding (Alternative)

Exception context objects on stack, unwinding performed by pushing unwinding instructions.

---

## Integration with GIMPLE Codegen

### Try Statement Detection

Codegen detects try statements early to:
1. Determine if function needs exception-safe cleanup
2. Allocate temporary for exception context ID
3. Create basic blocks for try/handler/finally/after paths

### Exception-Safe Variable Initialization

Functions containing try statements require exception-safe variable initialization (allocate locals in closure struct on heap).

### Function Preamble

If function has try statement:
```c
// Allocate locals struct
struct Locals_foo *_locals = malloc(sizeof(struct Locals_foo));

// Initialize all locals to zero/null
memset(_locals, 0, sizeof(struct Locals_foo));

// ... function body ...

// Exception-safe cleanup on exit
free(_locals);
```

---

## Limitations and Future Work

### Current Implementation

- Exception types not distinguished (single exception type per context)
- No stack trace/traceback information
- No exception inheritance hierarchy
- Message-only exception carrying (limited data)

### Future Enhancements

1. **Typed Exceptions**: Store exception type tag alongside message
   ```c
   struct Exception {
       int type;        // Exception type ID
       char *msg;       // Message
       int code;        // Error code
   };
   ```

2. **Traceback Information**: Record call stack on raise
   ```c
   struct StackFrame {
       const char *func;
       int line;
   };
   
   struct Exception {
       StackFrame stack[MAX_DEPTH];
       int stack_len;
   };
   ```

3. **Exception Filters**: Fine-grained exception matching
   ```python
   try:
       op()
   except IndexError as e:
       handle_index_error()
   except ValueError as e:
       handle_value_error()
   ```

4. **Exception Chaining**: Link exceptions (cause/context)
   ```python
   try:
       op1()
   except err1:
       raise new_err from err1  # Chain to err1
   ```

---

**Specification Date**: 2026-04-28  
**Status**: Complete exception handling specification for try/except/finally lowering  
**Integration**: Referenced by gimple_codegen.py for statement lowering and runtime exception API
