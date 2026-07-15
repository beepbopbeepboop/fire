# Parser TODO — Test Suite & Examples Pass Rate

**319 / 333 files pass (95.8%)**  
14 failures across stdlib/test/ and examples/, grouped by root cause below.

Run: `python3 test_suite_check.py`

---

## Failing Files

| File | Error |
|------|-------|
| stdlib/test/asyncrt/test_cuda.mojo | `Expected NAME got KW('out')` |
| stdlib/test/builtin/test_simd.mojo | `Expected KW got COMMA(',')` |
| stdlib/test/builtin/test_slice.mojo | `Expected RBRACKET got COLON(':')` |
| stdlib/test/builtin/test_tuple.mojo | `Expected RPAREN got NAME('list')` |
| stdlib/test/collections/string/test_string.mojo | `Unexpected COLON(':')` |
| stdlib/test/collections/test_codepoint.mojo | `Expected RPAREN got NAME('codepoint')` |
| stdlib/test/collections/test_dict.mojo | `Expected RBRACE got KW('for')` |
| stdlib/test/collections/test_list.mojo | `Expected RBRACKET got COLON(':')` |
| stdlib/test/collections/test_set.mojo | `Expected RBRACE got KW('for')` |
| stdlib/test/format/test_tstring.mojo | `Unexpected COLON(':')` |
| stdlib/test/itertools/test_product.mojo | `Expected KW got COMMA(',')` |
| stdlib/test/python/test_python_object.mojo | `Unexpected COLON(':')` |
| stdlib/test/tempfile/test_tempfile.mojo | `Unexpected ARROW('->')` |
| examples/gpu-functions/reduction.mojo | `Expected COLON got KW('raises')` |

---

## Root Causes

### 1. Slice subscript notation — 3 files
`Expected RBRACKET got COLON` — the parser does not handle `:` inside `[...]`
as slice syntax.

Patterns seen:
```mojo
sliceable[1:"hello":4.0]   # test_slice
s[2::-1]                    # test_slice
seq[1:4]                    # test_list
str[byte=2:]                # test_string (named param + slice)
str[byte= -50::]            # test_string
```

Fix: extend subscript parsing to recognise `:` as a slice separator and
produce `Slice(start, stop, step)` AST nodes. Also handle named subscript
parameters combined with slice notation (`name=val:`).

**Files:** test_slice.mojo, test_list.mojo, test_string.mojo

---

### 2. `raises` and `capturing` qualifiers — 2 files
`Expected COLON got KW('raises')` / `Unexpected ARROW('->')`

The parser does not accept `raises` or `capturing` between the parameter list
and the body colon (or return-type arrow).

Patterns seen:
```mojo
def kernel_launch_sum(ctx: DeviceContext) raises:       # reduction
def sum_kernel_benchmark(...) capturing raises:         # reduction
var clean_up_function: def() raises -> None             # test_tempfile
def __exit__(mut self, error: Error) raises -> Bool:    # test_tempfile
```

Fix: allow `raises` (and optionally `capturing`) as optional qualifiers in
`parse_function_def` between `)` and `:` (or `->`). Also recognise
`def(...) raises -> T` as a valid function-type annotation.

**Files:** reduction.mojo, test_tempfile.mojo

---

### 3. Dict and set comprehensions — 2 files
`Expected RBRACE got KW('for')` — after parsing a `{expr}`, the parser does
not handle `for` to begin a comprehension.

Patterns seen:
```mojo
{k: v for k, v in some_dict.items()}   # test_dict
{x for x in collection}                # test_set
```

Fix: in `parse_dict_or_set_literal`, after the first expression, check for
`for` and parse a comprehension body instead of a literal element list.

**Files:** test_dict.mojo, test_set.mojo

---

### 4. Keyword names used as attribute identifiers — 2 files
`Expected KW got COMMA` — `DType.bool` is parsed as `DType` `.` KW(`bool`).
Inside a generic parameter list `[DType.bool, 4]` the parser expected another
keyword construct after `bool`, not a `,`.

Patterns seen:
```mojo
SIMD[DType.bool, 4](False, True, False, True).cast[DType.bool]()
SIMD[DType.int32, 4](0, 1, 0, 1)
product(l1, l2)   # test_product — similar KW-after-dot issue
```

Fix: in attribute access (`a.b`), always accept any keyword token as a valid
identifier after `.` (i.e. `NAME | KW` on the right-hand side of `.`).

**Files:** test_simd.mojo, test_product.mojo

---

### 5. `out` reserved as a keyword — 1 file
`Expected NAME got KW('out')` — `out` is in the keyword table and cannot be
used as a plain variable name.

Pattern seen:
```mojo
out = ctx.enqueue_create_buffer[DType.float32](LEN)   # used as variable
```

Fix: either demote `out` from the keyword table to a context-sensitive keyword
(only special in parameter position), or allow KW tokens where NAME is expected
in assignment targets.

**Files:** test_cuda.mojo

---

### 6. t-string literal prefix — 1 file
`Unexpected COLON` — the `t"..."` prefix is not recognised by the tokenizer.
It is likely split into `NAME('t')` + `STRING`, causing subsequent parse
failures when the body tries to use the result.

Pattern seen:
```mojo
writer.write(t"({self.x}, {self.y})")
t"Hello, {name}!"
```

Fix: add `t"..."` (and `t'...'`) as a recognised string-literal prefix in the
tokenizer, producing a `TSTRING` token (or reusing `FSTRING` infrastructure).

**Files:** test_tstring.mojo

---

### 7. Dict literal as expression — 1 file
`Unexpected COLON` — `{key: value, ...}` dict literals appear in call
arguments and assignment RHS positions where the parser does not attempt dict
literal parsing.

Pattern seen (test_python_object):
```mojo
assert_equal(String(py=dd), "{'food': 123}")  # string OK, but elsewhere:
var dd = {"food": 123, "fries": "yes"}        # or equivalent inline dict
```

Fix: ensure `parse_primary` / `parse_atom` enters dict-literal mode on `{`
when not in a block context; the colon inside `{k: v}` must be consumed as
part of the dict literal, not surfaced to the outer parser.

**Files:** test_python_object.mojo

---

### 8. `(var x) =` tuple destructuring — 1 file
`Expected RPAREN got NAME('list')` — the parser does not handle `var` inside
parentheses as a destructuring target.

Pattern seen:
```mojo
(var list) = [a + b for a, b in [(1, 2), (3, 4)]]
```

Note: `list` is also likely in the keyword table (same issue as `out` above —
the token returned is `NAME('list')`, so the tokenizer already handles it, but
the *outer* parse context expects `RPAREN` after some sub-expression rather
than accepting the full `(var name)` form).

Fix: add `(var <name>)` as a recognised assignment target in the statement
parser, alongside `var <name> =` and plain tuple unpacking.

**Files:** test_tuple.mojo

---

### 9. Multi-word identifier split at keyword boundary — 1 file
`Expected RPAREN got NAME('codepoint')` — `Codepoint(unsafe_unchecked_codepoint=32)`
fails, suggesting the tokenizer splits `unsafe_unchecked_codepoint` at some
internal keyword boundary (possibly `unsafe`), leaving `_unchecked_codepoint`
and then the partial match `codepoint` as a separate token.

Fix: audit the tokenizer for greedy keyword matching that breaks identifiers
containing keyword prefixes (e.g. `unsafe`, `out`, `bool`). Identifiers must
always be tokenized as the longest alphanumeric+underscore sequence before
checking for keyword membership.

**Files:** test_codepoint.mojo

---

## Priority Order for Next Sprint

| Priority | Root Cause | Files Fixed |
|----------|-----------|-------------|
| 1 | Slice subscript notation | 3 |
| 2 | Dict/set comprehensions | 2 |
| 3 | Keyword names as attribute identifiers | 2 |
| 4 | `raises`/`capturing` qualifiers | 2 |
| 5 | `out` as identifier (keyword conflict) | 1 |
| 6 | Identifier split at keyword boundary | 1 |
| 7 | t-string prefix | 1 |
| 8 | Dict literal as expression | 1 |
| 9 | `(var x) =` destructuring | 1 |
