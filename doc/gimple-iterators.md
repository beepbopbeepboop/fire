# GIMPLE Iterator Protocol Specification

Specification for lowering Mojo `for` loops over containers and user-defined iterators.

Source: Extracted from gimple_codegen.py iterator lowering (lines 1905-1912, 2167-2504).

---

## Overview

GIMPLE supports three categories of iteration:

1. **Range iteration** — `for i in range(start, stop, step)`
2. **Container iteration** — `for x in list/dict/set/str`
3. **Struct iterator protocol** — `for x in obj` where `obj` has `__iter__`, `__has_next__`, `__next__`

---

## Range Iteration

### Mojo Syntax

```mojo
for i in range(10):
    print(i)

for i in range(1, 11):
    print(i)

for i in range(0, 100, 5):
    print(i)
```

### GIMPLE Lowering

Range loops are expanded to manual counter loops with explicit bounds checking.

#### Single argument: `range(stop)`

Expands to `range(0, stop, 1)`:

```c
int i = 0;
goto L_cond;

L_cond:
  _cond = i < stop_val;
  if (_cond) goto L_body; else goto L_after;

L_body:
  // loop body
  goto L_post;

L_post:
  _step_t = i + 1;
  i = _step_t;
  goto L_cond;

L_after:
  // continue after loop
```

#### Two arguments: `range(start, stop)`

Expands to `range(start, stop, 1)`:

```c
int i = start_val;
goto L_cond;

L_cond:
  _cond = i < stop_val;
  if (_cond) goto L_body; else goto L_after;

L_body:
  // loop body
  goto L_post;

L_post:
  _step_t = i + 1;
  i = _step_t;
  goto L_cond;

L_after:
```

#### Three arguments: `range(start, stop, step)`

Step direction determines comparison operator:

- **Positive step** (`step > 0`): Use `i < stop` condition
- **Negative step** (`step < 0`): Use `i > stop` condition
- **Dynamic step** (not compile-time constant): Compute both `<` and `>`, select based on sign

**Example: Positive step**:
```c
int i = 0;
goto L_cond;

L_cond:
  _cond = i < stop_val;
  if (_cond) goto L_body; else goto L_after;

L_body:
  // loop body
  goto L_post;

L_post:
  _step_t = i + step_val;
  i = _step_t;
  goto L_cond;

L_after:
```

**Example: Negative step**:
```c
int i = 100;
goto L_cond;

L_cond:
  _cond = i > stop_val;
  if (_cond) goto L_body; else goto L_after;

L_body:
  // loop body
  goto L_post;

L_post:
  _step_t = i + step_val;    // step_val is negative
  i = _step_t;
  goto L_cond;

L_after:
```

**Example: Dynamic step**:
```c
int i = 0;
goto L_cond;

L_cond:
  _t_lt = i < stop_val;
  _t_gt = i > stop_val;
  _t_spos = step_val > 0;
  _cond = _t_spos ? _t_lt : _t_gt;
  if (_cond) goto L_body; else goto L_after;

L_body:
  // loop body
  goto L_post;

L_post:
  _step_t = i + step_val;
  i = _step_t;
  goto L_cond;

L_after:
```

---

## Container Iteration

### Overview

Containers (`MojoList`, `MojoDict`, `MojoSet`, `MojoStr`) have built-in iteration support.

### List Iteration

#### Mojo Syntax

```mojo
numbers = [1, 2, 3]
for n in numbers:
    print(n)
```

#### GIMPLE Lowering

Uses index-based iteration with `mojo_list_len()` and `mojo_list_get_*()`:

```c
MojoList *_numbers = ...;
int _n;
int64_t _len64;
int _len;
int _idx;

_len64 = mojo_list_len(_numbers);
_len = (int)_len64;
_idx = 0;
goto L_cond;

L_cond:
  _cond = _idx < _len;
  if (_cond) goto L_body; else goto L_after;

L_body:
  int64_t _idx64 = (int64_t)_idx;
  _n = (int)mojo_list_get_int(_numbers, _idx64);  // Get element
  // loop body
  goto L_post;

L_post:
  _step = _idx + 1;
  _idx = _step;
  goto L_cond;

L_after:
```

**Type-specific extraction**:
- `int` elements: `mojo_list_get_int(list, idx)` → cast to element type
- `double` elements: `mojo_list_get_double(list, idx)` → direct assignment
- `char *` elements: `mojo_list_get_str(list, idx)` → direct assignment

### String Iteration

#### Mojo Syntax

```mojo
text = "hello"
for ch in text:
    print(ch)
```

#### GIMPLE Lowering

Similar to list iteration, using `mojo_str_len()` and `mojo_str_char_at()`:

```c
MojoStr *_text = ...;
char _ch;
int64_t _len64;
int _len;
int _idx;

_len64 = mojo_str_len(_text);
_len = (int)_len64;
_idx = 0;
goto L_cond;

L_cond:
  _cond = _idx < _len;
  if (_cond) goto L_body; else goto L_after;

L_body:
  int64_t _idx64 = (int64_t)_idx;
  _ch = mojo_str_char_at(_text, _idx64);  // Get character
  // loop body
  goto L_post;

L_post:
  _step = _idx + 1;
  _idx = _step;
  goto L_cond;

L_after:
```

### Dictionary Iteration

#### Mojo Syntax

```mojo
config = {"key1": 1, "key2": 2}
for key in config:
    print(key)
```

#### GIMPLE Lowering

Uses dictionary iterator protocol with `mojo_dict_iter_*()` functions:

```c
MojoDict *_config = ...;
char *_key;
MojoDictIter *_iter;

_iter = mojo_dict_iter_new(_config);
goto L_cond;

L_cond:
  _has_next = mojo_dict_iter_next(_iter);
  _cond = (_has_next != 0);
  if (_cond) goto L_body; else goto L_after;

L_body:
  _key = mojo_dict_iter_key(_iter);  // Get current key
  // loop body
  goto L_post;

L_post:
  goto L_cond;

L_after:
  mojo_dict_iter_free(_iter);
```

**Note**: If accessing both key and value:
```c
_key = mojo_dict_iter_key(_iter);
_val = mojo_dict_iter_val_int(_iter);  // Type-specific value access
```

### Set Iteration

#### Mojo Syntax

```mojo
unique = {1, 2, 3}
for item in unique:
    print(item)
```

#### GIMPLE Lowering

Similar to dict iteration using `mojo_set_iter_*()`:

```c
MojoSet *_unique = ...;
int64_t _item;
MojoSetIter *_iter;

_iter = mojo_set_iter_new(_unique);
goto L_cond;

L_cond:
  _has_next = mojo_set_iter_next(_iter);
  _cond = (_has_next != 0);
  if (_cond) goto L_body; else goto L_after;

L_body:
  _item = mojo_set_iter_val_int(_iter);  // Get current element
  // loop body
  goto L_post;

L_post:
  goto L_cond;

L_after:
  mojo_set_iter_free(_iter);
```

---

## Struct Iterator Protocol

### Overview

User-defined types can implement iterator methods for custom iteration behavior.

### Iterator Methods

Three methods define iterator protocol on struct `StructName`:

1. **`StructName___iter__(obj: StructName *) → IteratorType *`**
   - Creates iterator state from object
   - May return same type or separate iterator struct
   - Optional; if missing, iterator is the object itself

2. **`StructName___has_next__(iter: IteratorType *) → int`**
   - Returns 1 if more elements, 0 at end
   - Called at start of each iteration

3. **`StructName___next__(iter: IteratorType *) → ElementType`**
   - Returns next element value
   - Called if `__has_next__` returns 1

### Example: Struct with Iterator Protocol

```mojo
struct Range:
    start: Int
    stop: Int
    
    fn __iter__(self) -> RangeIter:
        return RangeIter(self.start, self.stop)
    
struct RangeIter:
    current: Int
    stop: Int
    
    fn __has_next__(self) -> Bool:
        return self.current < self.stop
    
    fn __next__(self) -> Int:
        result = self.current
        self.current = self.current + 1
        return result
```

### GIMPLE Lowering

#### Case 1: Separate Iterator Type (has `__iter__`)

```mojo
r = Range(0, 10)
for i in r:
    print(i)
```

Generates:

```c
Range *_r = ...;
int _i;
RangeIter *_iter;

// Call __iter__ to get iterator
_iter = Range___iter__(_r);

goto L_cond;

L_cond:
  _has_next = RangeIter___has_next__(_iter);
  _cond = (_has_next != 0);
  if (_cond) goto L_body; else goto L_after;

L_body:
  _i = RangeIter___next__(_iter);
  // loop body
  goto L_post;

L_post:
  goto L_cond;

L_after:
  // no cleanup for returned iterator (would need destructor)
```

#### Case 2: Self-Iterator (no `__iter__`)

```mojo
struct Array:
    data: Int *
    len: Int
    idx: Int  // mutable iterator state
    
    fn __has_next__(self) -> Bool:
        return self.idx < self.len
    
    fn __next__(self) -> Int:
        result = self.data[self.idx]
        self.idx = self.idx + 1
        return result

arr: Array = ...
for elem in arr:
    print(elem)
```

Generates:

```c
Array *_arr = ...;
int _elem;

// No __iter__ call; use object directly as iterator

goto L_cond;

L_cond:
  _has_next = Array___has_next__(_arr);
  _cond = (_has_next != 0);
  if (_cond) goto L_body; else goto L_after;

L_body:
  _elem = Array___next__(_arr);
  // loop body
  goto L_post;

L_post:
  goto L_cond;

L_after:
```

### Dispatch Logic

Given `for x in obj` where `obj` has type `StructType *`:

1. **Check for `StructType___iter__`**:
   - If found: Call it to get iterator
   - Infer iterator type from `__iter__` return type
   - Use returned iterator in loop

2. **Otherwise**: Use `obj` directly as iterator

3. **Check for `___has_next__` on iterator type**:
   - If found: Call it at loop condition
   - If not found: Emit TODO comment, set condition to false

4. **Check for `___next__` on iterator type**:
   - If found: Call it in loop body to get next element
   - If not found: Emit TODO comment

---

## Iteration Control Flow

### Break Statement

Break jumps to label after the loop:

```mojo
for i in range(10):
    if i == 5:
        break
    print(i)
```

Generates:

```c
for_loop:
  if (i == 5) goto L_after; else goto L_continue;

L_after:
  // continue after loop
```

Loop stack maintains `(continue_label, break_label)` pairs for nested loops.

### Continue Statement

Continue jumps to post-iteration label:

```mojo
for i in range(10):
    if i == 5:
        continue
    print(i)
```

Generates:

```c
for_loop:
  // loop body
  if (i == 5) goto L_post; else goto L_body;

L_body:
  print(i);
  goto L_post;

L_post:
  // post-iteration (step or next check)
  goto L_cond;
```

---

## Comprehensions

### List Comprehension

```mojo
result = [x * 2 for x in nums if x > 0]
```

Lowers to:

```c
MojoList *_result = mojo_list_new();
for (int _x = 0; _x < mojo_list_len(nums); _x++) {
    int _elem = mojo_list_get_int(nums, _x);
    if (_elem > 0) {
        mojo_list_append_int(_result, _elem * 2);
    }
}
```

### Set Comprehension

```mojo
result = {x for x in nums}
```

Lowers to:

```c
MojoSet *_result = mojo_set_new();
for (int _x = 0; _x < mojo_list_len(nums); _x++) {
    int _elem = mojo_list_get_int(nums, _x);
    mojo_set_add_int(_result, _elem);
}
```

### Dict Comprehension

```mojo
result = {k: v * 2 for k, v in pairs}
```

Lowers to (iterating over dict):

```c
MojoDict *_result = mojo_dict_new();
MojoDictIter *_iter = mojo_dict_iter_new(pairs);
while (mojo_dict_iter_next(_iter)) {
    char *_k = mojo_dict_iter_key(_iter);
    int _v = mojo_dict_iter_val_int(_iter);
    mojo_dict_set_int(_result, _k, _v * 2);
}
mojo_dict_iter_free(_iter);
```

---

## Loop Annotations for Optimization

### GIMPLE Loop Count Hints

Loops are emitted with GIMPLE `count()` annotations to guide branch prediction and optimization:

```c
bb_2:
  _cond = _i < _stop;
  if (_cond) goto bb_3 _with_count(1000000); else goto bb_after;

bb_3 __attribute__((count(1000000))):
  // loop body
```

The count is a guess based on nesting depth: `10 ** loop_depth`.

---

## Integration with GIMPLE Codegen

### Iteration Dispatch

When codegen sees a `for` statement:

```python
if isinstance(node.iterable, CallExpr) and node.iterable.func.name == 'range':
    self._gen_for_range(node)
else:
    self._gen_for_iter(node)
```

### Container Type Dispatch

For non-range iteration, dispatch by container type:

```python
if it_type == 'MojoList *':
    self._gen_for_list(var, it_val, node.body)
elif it_type == 'MojoStr *':
    self._gen_for_str(var, it_val, node.body)
elif it_type == 'MojoDict *':
    self._gen_for_dict(var, it_val, node.body)
elif it_type == 'MojoSet *':
    self._gen_for_set(var, it_val, node.body)
elif it_type.endswith(' *'):
    # Struct iterator protocol
    self._gen_for_struct_iter(var, it_type, it_val, node.body)
```

---

## Limitations and Future Work

### Current Implementation

1. **No iterator state**: Iterator methods modify object in-place (not functional)
2. **No async iteration**: No support for async iterators
3. **No unpacking**: Cannot do `for a, b in pairs` for tuples
4. **Single iterator protocol**: All user iterators must implement `__iter__`, `__has_next__`, `__next__`

### Future Enhancements

1. **Multiple dispatch**: Support different iterator interfaces (Rust-style `IntoIterator`)

2. **Unpacking in for loop**:
   ```mojo
   for (key, value) in dict.items():
       print(key, value)
   ```

3. **Async iteration**:
   ```mojo
   async for item in async_iterable:
       await process(item)
   ```

4. **Iterator expressions** (generators):
   ```mojo
   gen = (x * 2 for x in nums)
   for item in gen:
       print(item)
   ```

5. **Functional composition**: Chaining iterators without intermediate lists

---

**Specification Date**: 2026-04-28  
**Status**: Complete iterator protocol specification for range/container/struct iteration  
**Integration**: Referenced by gimple_codegen.py for for-loop lowering
