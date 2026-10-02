# FORMAL_struct_eq_compares_frame_addresses: `x == y` on a struct is an integer comparison of the two frame addresses

**Status: OPEN, found 2026-09-30 while landing
`bugs/FORMAL_method_param_field_access.md` (now fixed and `git rm`'d), and
measured there for the first time — that file recorded it as an open question
and said explicitly that it was NOT measured on this tree. Not fixed here: it
is the OPERATOR's dispatch, not a parameter's field, and no test in this tree
dispatches a struct comparison.**

A struct that declares `__eq__` compares by ADDRESS. Two distinct objects with
identical contents compare unequal, silently, on both architectures, and the
program exits 0 — which is the outcome this whole backend exists to make
impossible, and the only one of its kinds that is not a refusal today.

## What I ran

```mojo
struct Pair:
    var a: Int
    var b: Int
    def __eq__(self, other: Pair) -> Bool:
        return self.a == other.a and self.b == other.b

def main(n: Int) -> Int:
    var x = Pair()
    var y = Pair()
    x.a = 1
    x.b = 2
    y.a = 1
    y.b = 2
    if x == y:
        return 1
    return 0
```

```
$ python3 fire.py build --formal --no-prove -o eq2.aout eq2.mojo
Built: eq2.aout  [arm64/macho]
$ ./eq2.aout; echo $?
0                      # the source says 1
$ python3 fire.py build --formal --no-prove --backend x86_64 -o eq2.x86 eq2.mojo
Built: eq2.x86  [x86_64/macho]
$ arch -x86_64 ./eq2.x86; echo $?
0                      # the source says 1
```

CPython on the same program, with the struct as a class and `__eq__` as
`__eq__`, returns 1. Both backends agree with each other and both are wrong,
which is what makes it easy to miss: a two-backend comparison cannot see it,
because the defect is shared.

The same program with `x.__eq__(y)` written out returns 1 on both backends —
so the method itself lowers and answers correctly. Only the OPERATOR spelling
is wrong, which is what makes this a dispatch question rather than a field one.

## Why

`_emit_binop`'s `cmp_conds` (`formal/arm64_codegen.py:4129`, and the matching
table in `formal/x86_64_codegen.py`) has no struct case: `==` becomes the
flag-setting integer compare, `_emit_cmp(e.left, e.right, "eq", "eq")`, and both
operands are the frame ADDRESSES the by-reference receiver hands around
(`bugs/FORMAL_wide_receiver_by_reference.md`). Two objects built by two
`Pair()` calls are two frames at two addresses, so the compare is false; one
object compared with ITSELF is true, which is why a smoke test that writes
`x == x` sees nothing.

There is a string arm immediately above it — `self._emit_strcmp_flags` — so the
shape of the fix is visible in the file: an operand-kind arm that intercepts
the operator and emits something other than an integer compare. For a struct
that arm would be `_rewrite_method_calls`' `Pair___eq__`, which already exists
and already takes the receiver first; `x == y` on a struct is `Pair___eq__(x,
y)` and returns a Bool in a register.

## The exact next step

1. **Which operators.** `==` and `!=` are the pair that has to agree with each
   other; `!=` is its negation of the same dispatch. `<`, `>` and friends have
   no answer for a struct in this value model at all, and refusing them
   (`model.string_binary_refusal`'s sibling for a frame operand) is the honest
   thing rather than comparing addresses in the other direction.
2. **Which structs.** A struct whose receiver is a FRAME of this module and
   which declares `__eq__` — the same two questions
   `model.struct_dunder_len_candidates` already asks for `len` and
   `_rewrite_len_on_frame_receivers` acts on, for the same reason: the callee
   exists, it takes the receiver first, and the frame address is exactly what
   it wants. A struct with NO `__eq__` is the interesting half, because Python's
   answer there is IDENTITY (`x == x` true, `x == y` false for two objects) and
   that IS what the address compare computes — so the fix must not change it,
   and the one-field case is not an address at all.
3. **The rewrite cannot go where `len`'s does not.** `_rewrite_method_calls`
   runs before any frame analysis exists, and at that point nothing knows that
   `x` is a frame rather than a word, so `==` on an ordinary value — a string, an
   Int — must keep reaching the integer and `strcmp` lowerings. The place that
   already knows is `_frame_receivers`, beside
   `_rewrite_len_on_frame_receivers` and for the same reason; see that
   function's docstring for the one-edge argument the rewrite introduces.
4. **The test has to be both directions.** A case that checks `x == y` for two
   equal objects is satisfied by an answer that is right for the wrong reason
   (identity), so the suite needs `x != y` after one field is changed as well,
   and a one-field struct as a control.

This is the construct that makes `Slice(1,2,3) == Slice(1,2,3)` — the first
example in `builtin_slice.mojo`'s own docstring — answer false on a correct
build, so it is worth its own doc rather than a line in the parameter one.