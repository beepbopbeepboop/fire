# FORMAL_string_equality_of_two_unclassified_words: `==` on two computed strings compares ADDRESSES

**Status:** open. Found while writing `os`; the kind table is
`formal/model.py`'s and `ValueKinds` is not this task's file. It is the worst
shape a backend bug can have — a correct program taking the wrong branch — and
it is silent on both architectures.

## What I ran

```
$ cat > .tmp/rq.mojo
def mk(t):
    var p: Pointer[UInt8] = malloc(64)
    snprintf(p, 64, "%s", t)
    return p

def main(n):
    a = "abc"
    b = "abc"
    printf("lit-lit=%d@",   1 if a == b else 0)
    c = mk("abc")
    d = mk("abc")
    printf("call-call=%d@", 1 if c == d else 0)
    e = mk("abc")
    printf("call-lit=%d@",  1 if e == a else 0)
    printf("nc=%d@",  strncmp(c, d, strlen(d) + 1))
    printf("nc2=%d@", strncmp(c, d, 4))
    return 0
```

## What I saw

```
lit-lit=1@call-call=0@call-lit=1@nc=0@nc2=0@
```

`c` and `d` are two separately-allocated buffers with the same four bytes, and
`c == d` is **FALSE** — while `strncmp(c, d, strlen(d) + 1)`, the very call the
lowering is supposed to make, returns 0. The three rows together localise it
exactly:

| row | what it says |
|---|---|
| `lit-lit=1` | two interned literals compare equal — interning makes them one object, so even a pointer compare would pass |
| `call-call=0` | **the defect.** Two equal strings, one comparison, FALSE |
| `call-lit=1` | one side being a call result is enough to be classified a string |
| `nc=0` | the content compare that `==` is documented to lower to agrees they are equal |

So the content compare is not mis-LOWERED; it is never REACHED.

## Why

`formal/model.py:string_comparison_lowering` (`:1119`) opens with

```python
if not (string_operand_is_string(left_kind)
        or string_operand_is_string(right_kind)):
    return None
```

and the caller's fallback for `None` is the ordinary integer comparison of two
words. A value that arrived from a call is classified `INT_KIND` — there is no
declared type to read — so with BOTH sides unclassified neither is a string,
`string_comparison_lowering` returns `None`, and `==` becomes a pointer
compare. `call-lit=1` passes only because the literal on the right is a string,
which is enough for the `or`.

The two halves of `call-call` are therefore the same fact as the bullet
"`_rhs_pointee` sees an unannotated parameter as a word" in
`bugs/FORMAL_string_value_model.md`'s residue: the kind of a value that came
out of a call is not recovered from the callee. That document records it for
`if s:` and for a comprehension's loop variable; `==` is the same gap with a
worse consequence, and it is the operator a path library uses most.

## What I expected

`call-call=1`. Two `char *` into two `malloc`'d buffers, compared with
`strncmp(a, b, strlen(b) + 1) == 0`, which is what the function that handles
this case says it does.

## The exact next step

Propagate the CALLEE's return kind to the call site, the way
`string_operand_is_string` already needs it, and make the fallback for two
unclassified words a REFUSAL rather than a word compare:

1. `function_return_str_kind(fn, name)` in `formal/model.py`, beside
   `_rhs_pointee`'s fourth case ("a call to a function of this image whose own
   RETURN ANNOTATION is a string"), extended to read the annotation off the
   imported module's source for a callee in a dylib — `formal/imports.py`'s
   `declared_kinds` is the reader, and it already parses the module the
   library was built from. **This needs the ANNOTATIONS to exist first**:
   `os` and `os.path` declare no return types today, because nothing consumed
   them, so the first half of the fix is `-> str` on the thirty-odd functions
   of `os` that return a string and a `-> int` on the ones that do not. That
   half is a one-line-per-function change to a module that is otherwise
   finished, which is the cheapest thing in this document.
2. Until (1) exists, `string_binary_refusal` for `==`/`!=` with BOTH operands
   unclassified and at least one of them a call result, rather than the silent
   word compare. This is the half that is cheap and it converts a wrong branch
   into a diagnostic; a program that tests two computed strings for equality is
   common enough that the diagnostic will fire, which is the point.

**Note for anyone working around it today**, which is what `os` does: ask the
question with a bounded compare, not with `==`. `os/_syscalls.mojo:str_eq_n`
(`memcmp(a, b, n) == 0`) and `str_starts` (`strncmp`) are the shapes to copy.
`test_formal_os.py` prints both sides of the one comparison it would have made
and compares the strings in Python rather than asserting the boolean the
program computes — a test that asserts a wrong answer is worse than no test.
