# GIMPLE Runtime API Specification

Specification for the C runtime library that supports GIMPLE code generation for Mojo containers, exceptions, and string operations.

Source: Extracted from gimple_codegen.py runtime function declarations and call patterns.

---

## Overview

The GIMPLE runtime provides:
- **Container APIs**: `MojoList`, `MojoDict`, `MojoSet` — dynamic containers with typed element access
- **String API**: `MojoStr` — immutable string type with operations
- **Exception API**: Exception context stack management and message handling
- **Iterator Protocol**: Dict and set iteration support
- **Memory Helpers**: Pointer dereferencing at specific types

All functions are C declarations emitted as `extern` when used, with implementations provided by a linked runtime library (not included in this specification).

---

## Type Definitions

### Container Types (Opaque)

```c
typedef struct MojoList    MojoList;     // Dynamic list container
typedef struct MojoDict    MojoDict;     // Hash map container
typedef struct MojoSet     MojoSet;      // Hash set container
typedef struct MojoStr     MojoStr;      // String container
typedef struct MojoDictIter MojoDictIter;  // Dict iteration state
typedef struct MojoSetIter  MojoSetIter;   // Set iteration state
```

---

## MojoList API

Dynamically resizable list container. Stores homogeneous elements (type determined at creation time).

### List Creation

#### `mojo_list_new() → MojoList *`

Create empty list.

**Return**: Pointer to new, empty list.

**Example**:
```c
MojoList *nums = mojo_list_new();
```

### List Length

#### `mojo_list_len(list: MojoList *) → int64_t`

Get number of elements in list.

**Parameters**:
- `list`: List to query

**Return**: Number of elements (0 if empty, ≥0)

**Example**:
```c
int64_t len = mojo_list_len(nums);  // len = 0 for new list
```

### List Element Access (Read)

#### `mojo_list_get_int(list: MojoList *, index: int64_t) → int64_t`

Get integer element at index.

**Parameters**:
- `list`: List to query
- `index`: Zero-based index (0 ≤ index < len)

**Return**: Element value at index

**Error behavior**: Undefined if index out of bounds

**Example**:
```c
int64_t val = mojo_list_get_int(nums, 0);
```

#### `mojo_list_get_double(list: MojoList *, index: int64_t) → double`

Get floating-point element at index.

**Parameters**:
- `list`: List to query
- `index`: Zero-based index

**Return**: Element value at index

#### `mojo_list_get_str(list: MojoList *, index: int64_t) → char *`

Get string element at index (pointer, not a copy).

**Parameters**:
- `list`: List to query
- `index`: Zero-based index

**Return**: Pointer to element string (do not free)

### List Element Access (Write)

#### `mojo_list_set_int(list: MojoList *, index: int64_t, value: int64_t) → void`

Set integer element at index.

**Parameters**:
- `list`: List to modify
- `index`: Zero-based index (0 ≤ index < len)
- `value`: New element value

**Precondition**: index must be < current length

**Example**:
```c
mojo_list_set_int(nums, 0, 42);
```

#### `mojo_list_set_double(list: MojoList *, index: int64_t, value: double) → void`

Set floating-point element at index.

#### `mojo_list_set_str(list: MojoList *, index: int64_t, value: char *) → void`

Set string element at index.

**Note**: Value is copied into list; caller retains ownership of passed string.

### List Membership

#### `mojo_list_contains_int(list: MojoList *, value: int64_t) → int`

Check if list contains integer value.

**Return**: 1 if value found, 0 otherwise

**Example**:
```c
int found = mojo_list_contains_int(nums, 42);
```

#### `mojo_list_contains_double(list: MojoList *, value: double) → int`

Check if list contains floating-point value.

#### `mojo_list_contains_str(list: MojoList *, value: char *) → int`

Check if list contains string value.

### List Manipulation

#### `mojo_list_append_int(list: MojoList *, value: int64_t) → void`

Append integer element to end of list.

**Parameters**:
- `list`: List to modify
- `value`: Element to append

**Effect**: Extends list length by 1

**Example**:
```c
mojo_list_append_int(nums, 42);
```

#### `mojo_list_append_double(list: MojoList *, value: double) → void`

Append floating-point element to end of list.

#### `mojo_list_append_str(list: MojoList *, value: char *) → void`

Append string element to end of list.

**Note**: Value is copied into list.

#### `mojo_list_slice(list: MojoList *, start: int64_t, end: int64_t) → MojoList *`

Create new list from slice of existing list.

**Parameters**:
- `list`: Source list
- `start`: Start index (inclusive)
- `end`: End index (exclusive)

**Return**: New list containing elements [start, end)

**Semantics**: Python slice semantics; negative indices not supported in spec.

**Example**:
```c
MojoList *sub = mojo_list_slice(nums, 0, 2);  // [nums[0], nums[1]]
```

#### `mojo_list_concat(list1: MojoList *, list2: MojoList *) → MojoList *`

Create new list from concatenation of two lists.

**Parameters**:
- `list1`: First list
- `list2`: Second list

**Return**: New list containing all elements of list1 followed by list2

**Precondition**: Both lists must have same element type

**Example**:
```c
MojoList *combined = mojo_list_concat(nums, nums);
```

---

## MojoDict API

Hash map container. Stores key-value pairs with string keys and typed values.

### Dict Creation

#### `mojo_dict_new() → MojoDict *`

Create empty dictionary.

**Return**: Pointer to new, empty dict

**Example**:
```c
MojoDict *config = mojo_dict_new();
```

### Dict Length

#### `mojo_dict_len(dict: MojoDict *) → int64_t`

Get number of key-value pairs in dict.

**Return**: Number of entries (0 if empty)

### Dict Element Access (Read)

#### `mojo_dict_get_int(dict: MojoDict *, key: char *) → int64_t`

Get integer value for key.

**Parameters**:
- `dict`: Dict to query
- `key`: Key to look up (string)

**Return**: Value if key found; behavior undefined if key not found

**Example**:
```c
int64_t count = mojo_dict_get_int(config, "count");
```

#### `mojo_dict_get_double(dict: MojoDict *, key: char *) → double`

Get floating-point value for key.

#### `mojo_dict_get_str(dict: MojoDict *, key: char *) → char *`

Get string value for key (pointer, not a copy).

**Return**: Pointer to value string (do not free)

### Dict Membership

#### `mojo_dict_contains(dict: MojoDict *, key: char *) → int`

Check if dict contains key.

**Return**: 1 if key found, 0 otherwise

**Example**:
```c
if (mojo_dict_contains(config, "debug")) { ... }
```

### Dict Element Access (Write)

#### `mojo_dict_set_int(dict: MojoDict *, key: char *, value: int64_t) → void`

Set integer value for key (insert if new, update if exists).

**Parameters**:
- `dict`: Dict to modify
- `key`: Key (string)
- `value`: New value

**Effect**: Creates or updates key-value pair

**Example**:
```c
mojo_dict_set_int(config, "count", 42);
```

#### `mojo_dict_set_double(dict: MojoDict *, key: char *, value: double) → void`

Set floating-point value for key.

#### `mojo_dict_set_str(dict: MojoDict *, key: char *, value: char *) → void`

Set string value for key.

**Note**: Key and value are both copied into dict.

### Dict Iteration

#### `mojo_dict_iter_new(dict: MojoDict *) → MojoDictIter *`

Create new iterator over dict entries.

**Parameters**:
- `dict`: Dict to iterate

**Return**: Pointer to iterator state

**Lifetime**: Iterator valid until dict is modified or freed; must be freed with `mojo_dict_iter_free()`

**Example**:
```c
MojoDictIter *it = mojo_dict_iter_new(config);
while (mojo_dict_iter_next(it)) {
    char *key = mojo_dict_iter_key(it);
    int64_t val = mojo_dict_iter_val_int(it);
}
mojo_dict_iter_free(it);
```

#### `mojo_dict_iter_next(iter: MojoDictIter *) → int`

Advance iterator to next entry.

**Return**: 1 if entry available, 0 at end

**Semantics**: Call once before accessing first entry; return 0 when past last entry

**Example**:
```c
while (mojo_dict_iter_next(it)) {
    // Process current entry
}
```

#### `mojo_dict_iter_key(iter: MojoDictIter *) → char *`

Get key of current entry (valid only after `mojo_dict_iter_next()` returns 1).

**Return**: Pointer to key string (do not free)

#### `mojo_dict_iter_val_int(iter: MojoDictIter *) → int64_t`

Get integer value of current entry.

#### `mojo_dict_iter_val_double(iter: MojoDictIter *) → double`

Get floating-point value of current entry.

#### `mojo_dict_iter_val_str(iter: MojoDictIter *) → char *`

Get string value of current entry (pointer, not a copy).

**Return**: Pointer to value string (do not free)

#### `mojo_dict_iter_free(iter: MojoDictIter *) → void`

Free iterator state.

**Precondition**: Iterator must have been created with `mojo_dict_iter_new()`

**Example**:
```c
mojo_dict_iter_free(it);
```

---

## MojoSet API

Hash set container. Stores unique elements of a single type.

### Set Creation

#### `mojo_set_new() → MojoSet *`

Create empty set.

**Return**: Pointer to new, empty set

**Example**:
```c
MojoSet *unique = mojo_set_new();
```

### Set Membership

#### `mojo_set_contains_int(set: MojoSet *, value: int64_t) → int`

Check if set contains integer value.

**Return**: 1 if value in set, 0 otherwise

**Example**:
```c
if (mojo_set_contains_int(unique, 42)) { ... }
```

#### `mojo_set_contains_str(set: MojoSet *, value: char *) → int`

Check if set contains string value.

### Set Size

#### `mojo_set_len(set: MojoSet *) → int64_t`

Get number of unique elements in set.

**Return**: Number of elements (0 if empty)

### Set Manipulation

#### `mojo_set_add_int(set: MojoSet *, value: int64_t) → void`

Add integer to set (idempotent; no effect if already present).

**Parameters**:
- `set`: Set to modify
- `value`: Element to add

**Example**:
```c
mojo_set_add_int(unique, 42);
```

#### `mojo_set_add_str(set: MojoSet *, value: char *) → void`

Add string to set.

**Note**: Value is copied into set.

### Set Iteration

#### `mojo_set_iter_new(set: MojoSet *) → MojoSetIter *`

Create new iterator over set elements.

**Parameters**:
- `set`: Set to iterate

**Return**: Pointer to iterator state

**Lifetime**: Iterator valid until set is modified or freed; must be freed with `mojo_set_iter_free()`

**Example**:
```c
MojoSetIter *it = mojo_set_iter_new(unique);
while (mojo_set_iter_next(it)) {
    int64_t val = mojo_set_iter_val_int(it);
}
mojo_set_iter_free(it);
```

#### `mojo_set_iter_next(iter: MojoSetIter *) → int`

Advance iterator to next element.

**Return**: 1 if element available, 0 at end

#### `mojo_set_iter_val_int(iter: MojoSetIter *) → int64_t`

Get integer value of current element.

#### `mojo_set_iter_val_str(iter: MojoSetIter *) → char *`

Get string value of current element (pointer, not a copy).

**Return**: Pointer to value string (do not free)

#### `mojo_set_iter_free(iter: MojoSetIter *) → void`

Free iterator state.

---

## MojoStr API

Immutable string container with operations.

### String Creation

#### `mojo_str_new() → MojoStr *`

Create empty string.

**Return**: Pointer to new, empty string

#### `mojo_str_from_char(ch: char) → MojoStr *`

Create string from single character.

**Parameters**:
- `ch`: Character to convert

**Return**: Single-character string

### String Length

#### `mojo_str_len(str: MojoStr *) → int64_t`

Get length of string in characters.

**Return**: Number of characters (0 if empty)

### String Element Access

#### `mojo_str_char_at(str: MojoStr *, index: int64_t) → char`

Get character at index.

**Parameters**:
- `str`: String to query
- `index`: Zero-based index (0 ≤ index < len)

**Return**: Character at index

**Error behavior**: Undefined if index out of bounds

#### `mojo_str_data(str: MojoStr *) → char *`

Get raw C string pointer.

**Return**: Null-terminated C string (do not free)

**Lifetime**: Valid while `str` is alive

### String Membership

#### `mojo_str_contains(str: MojoStr *, needle: char *) → int`

Check if string contains substring.

**Parameters**:
- `str`: String to search
- `needle`: Substring to find

**Return**: 1 if needle found, 0 otherwise

### String Manipulation

#### `mojo_str_concat(str1: MojoStr *, str2: MojoStr *) → MojoStr *`

Create new string from concatenation.

**Return**: New string containing str1 followed by str2

**Example**:
```c
MojoStr *greeting = mojo_str_concat(hello, world);
```

#### `mojo_str_slice(str: MojoStr *, start: int64_t, end: int64_t) → MojoStr *`

Create substring from slice.

**Parameters**:
- `str`: Source string
- `start`: Start index (inclusive)
- `end`: End index (exclusive)

**Return**: New string containing characters [start, end)

**Example**:
```c
MojoStr *sub = mojo_str_slice(str, 0, 5);  // first 5 chars
```

#### `mojo_str_repeat(str: MojoStr *, count: int64_t) → MojoStr *`

Create new string from repetition.

**Parameters**:
- `str`: String to repeat
- `count`: Number of repetitions (≥0)

**Return**: New string containing str repeated count times

**Example**:
```c
MojoStr *stars = mojo_str_repeat(star, 10);
```

#### `mojo_str_eq(str1: MojoStr *, str2: MojoStr *) → int`

Check string equality.

**Return**: 1 if strings equal, 0 otherwise

### String Conversions

#### `mojo_str_to_int(str: MojoStr *) → int64_t`

Parse string as integer.

**Parameters**:
- `str`: String to parse

**Return**: Parsed integer value

**Error behavior**: Returns 0 if parse fails (no exception mechanism)

**Example**:
```c
int64_t num = mojo_str_to_int(numstr);
```

#### `mojo_str_to_float(str: MojoStr *) → double`

Parse string as floating-point number.

**Parameters**:
- `str`: String to parse

**Return**: Parsed floating-point value

**Error behavior**: Returns 0.0 if parse fails

---

## Exception API

Exception context stack for try/except handling. Exceptions are pushed onto a stack, caught by handlers, and popped on exit.

### Exception Context Management

#### `mojo_try_push() → int`

Push new exception context onto stack.

**Return**: Exception context ID (for matching with pop)

**Effect**: Creates new exception handler scope

**Example**:
```c
int exc_id = mojo_try_push();
// ... code that may raise
mojo_exc_pop();
```

#### `mojo_exc_pop() → void`

Pop exception context from stack.

**Precondition**: Must have matching `mojo_try_push()` call

**Effect**: Removes exception handler scope

**Exception handling**: If exception was pending, may trigger handler or propagate

### Exception Information

#### `mojo_exc_msg_set(msg: char *) → void`

Set exception message for current context.

**Parameters**:
- `msg`: Exception message (string, copied)

**Usage**: Called by exception handler to set descriptive message

**Example**:
```c
mojo_exc_msg_set("Division by zero");
```

#### `mojo_exc_msg_get() → char *`

Get exception message from current context.

**Return**: Pointer to exception message string (do not free)

**Default**: Empty string if no message set

### Exception Raising

#### `mojo_raise() → void`

Raise pending exception (exits current context, propagates to parent).

**Effect**: Terminates normal execution, jumps to exception handler

**Usage**: Called when exception condition detected

**Example**:
```c
if (divisor == 0) {
    mojo_exc_msg_set("Division by zero");
    mojo_raise();
}
```

---

## Pointer Dereferencing Helpers

Memory helpers for safe pointer dereferencing at specific types (generated on-demand for each type T used in program).

### Generic Pointer Dereference

#### `_mojo_at_T(ptr: T *) → T`

Dereference pointer to type T.

**Parameters**:
- `ptr`: Pointer to dereference

**Return**: Value at pointer

**Semantics**: Generates one instance per unique type T

**Examples**:
```c
_mojo_at_int(p)        // dereference int*
_mojo_at_double(p)     // dereference double*
_mojo_at_int64_t(p)    // dereference int64_t*
```

**Generated Code**:
```c
static inline T _mojo_at_T(T *ptr) {
    return *ptr;
}
```

**Usage in GIMPLE**: Emitted as helper functions when pointer types are dereferenced in expressions.

---

## Runtime Function Type Signatures (C Declaration Form)

### Complete function list for C extern declarations

```c
// Lists
extern MojoList *mojo_list_new(void);
extern int64_t mojo_list_len(MojoList *list);
extern int64_t mojo_list_get_int(MojoList *list, int64_t index);
extern double mojo_list_get_double(MojoList *list, int64_t index);
extern char *mojo_list_get_str(MojoList *list, int64_t index);
extern int mojo_list_contains_int(MojoList *list, int64_t value);
extern int mojo_list_contains_double(MojoList *list, double value);
extern int mojo_list_contains_str(MojoList *list, char *value);
extern void mojo_list_set_int(MojoList *list, int64_t index, int64_t value);
extern void mojo_list_set_double(MojoList *list, int64_t index, double value);
extern void mojo_list_set_str(MojoList *list, int64_t index, char *value);
extern void mojo_list_append_int(MojoList *list, int64_t value);
extern void mojo_list_append_double(MojoList *list, double value);
extern void mojo_list_append_str(MojoList *list, char *value);
extern MojoList *mojo_list_slice(MojoList *list, int64_t start, int64_t end);
extern MojoList *mojo_list_concat(MojoList *list1, MojoList *list2);

// Dicts
extern MojoDict *mojo_dict_new(void);
extern int64_t mojo_dict_len(MojoDict *dict);
extern int64_t mojo_dict_get_int(MojoDict *dict, char *key);
extern double mojo_dict_get_double(MojoDict *dict, char *key);
extern char *mojo_dict_get_str(MojoDict *dict, char *key);
extern int mojo_dict_contains(MojoDict *dict, char *key);
extern void mojo_dict_set_int(MojoDict *dict, char *key, int64_t value);
extern void mojo_dict_set_double(MojoDict *dict, char *key, double value);
extern void mojo_dict_set_str(MojoDict *dict, char *key, char *value);
extern MojoDictIter *mojo_dict_iter_new(MojoDict *dict);
extern int mojo_dict_iter_next(MojoDictIter *iter);
extern char *mojo_dict_iter_key(MojoDictIter *iter);
extern int64_t mojo_dict_iter_val_int(MojoDictIter *iter);
extern double mojo_dict_iter_val_double(MojoDictIter *iter);
extern char *mojo_dict_iter_val_str(MojoDictIter *iter);
extern void mojo_dict_iter_free(MojoDictIter *iter);

// Sets
extern MojoSet *mojo_set_new(void);
extern int mojo_set_contains_int(MojoSet *set, int64_t value);
extern int mojo_set_contains_str(MojoSet *set, char *value);
extern int64_t mojo_set_len(MojoSet *set);
extern void mojo_set_add_int(MojoSet *set, int64_t value);
extern void mojo_set_add_str(MojoSet *set, char *value);
extern MojoSetIter *mojo_set_iter_new(MojoSet *set);
extern int mojo_set_iter_next(MojoSetIter *iter);
extern int64_t mojo_set_iter_val_int(MojoSetIter *iter);
extern char *mojo_set_iter_val_str(MojoSetIter *iter);
extern void mojo_set_iter_free(MojoSetIter *iter);

// Strings
extern MojoStr *mojo_str_new(void);
extern int64_t mojo_str_len(MojoStr *str);
extern char mojo_str_char_at(MojoStr *str, int64_t index);
extern char *mojo_str_data(MojoStr *str);
extern int mojo_str_contains(MojoStr *str, char *needle);
extern MojoStr *mojo_str_concat(MojoStr *str1, MojoStr *str2);
extern MojoStr *mojo_str_slice(MojoStr *str, int64_t start, int64_t end);
extern MojoStr *mojo_str_repeat(MojoStr *str, int64_t count);
extern int mojo_str_eq(MojoStr *str1, MojoStr *str2);
extern int64_t mojo_str_to_int(MojoStr *str);
extern double mojo_str_to_float(MojoStr *str);
extern MojoStr *mojo_str_from_char(char ch);

// Exceptions
extern int mojo_try_push(void);
extern void mojo_exc_pop(void);
extern void mojo_exc_msg_set(char *msg);
extern char *mojo_exc_msg_get(void);
extern void mojo_raise(void);
```

---

## Implementation Notes

### Memory Management

- All functions returning pointers allocate memory (via malloc or arena)
- Returned pointers are valid until explicitly freed (for iterators) or until parent container is freed
- Strings returned from accessors (`.data()`, `.char_at()`) point into container; caller must not free
- Keys/values passed to insert functions are copied; caller retains ownership

### Type Safety

- Container functions are monomorphic in the C implementation (separate functions for each type: `_int`, `_double`, `_str`)
- Type mismatches between operations are not caught at runtime; behavior undefined
- GIMPLE code generator selects correct function based on inferred element type

### Exception Handling

- Exception stack is thread-local (or process-global in single-threaded runtime)
- `mojo_try_push()` / `mojo_exc_pop()` act as push/pop on a global stack
- `mojo_raise()` performs non-local jump (longjmp or equivalent)
- No stack unwinding; cleanup must be explicit in generated code

### Iterator Invalidation

- Iterators are invalidated if underlying container is modified
- Behavior undefined if container modified during iteration

---

## Integration with GIMPLE Codegen

### Declaration Generation

When gimple_codegen.py encounters a container operation, it emits an `extern` declaration for the required function(s):

```c
extern int mojo_list_append_int (MojoList *_t1, int64_t _t2);
```

### Function Call Lowering

Binary list operation `nums + [1, 2]` lowers to:

```c
MojoList *_t1 = mojo_list_concat(_t0, _t2);
```

### Type-Driven Function Selection

Element type determines which variant to call:

```
int element_type
  ↓
mojo_list_append_int() called
  
double element_type
  ↓
mojo_list_append_double() called
```

---

**Specification Date**: 2026-04-28  
**Status**: Complete runtime API specification for container/exception/string operations  
**Integration**: Referenced by gimple_codegen.py for function declaration and call generation
