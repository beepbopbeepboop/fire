# `printf("%s", <a container>)` prints the blob's COUNT byte, where CPython prints the container

**Area:** FORMAL, both backends — `formal/model.py`'s `printf` conversion
table. **Status: NOT FIXED**, and it is NOT the same defect as the `%d` one it
was found next to (`bugs/FORMAL_printf_d_of_a_container_prints_its_address.md`,
fixed and deleted 2026-10-05): that one is a program whose own source is WRONG,
so a refusal is the right answer, and this one is a program whose source is
RIGHT and the backend is short a capability.

## What I ran, what I saw, what I expected

```console
$ cat .tmp/sr.mojo
def main() -> Int32:
    var xs = [65, 66, 67]
    printf("L=[%s]\n", xs)
    var b = bytearray(3)
    b[0] = 65
    b[1] = 66
    b[2] = 67
    printf("B=[%s]\n", b)
    var d = {"a": 1}
    printf("D=[%s]\n", d)
    printf("len=%d\n", len(xs))
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/sr.arm64 .tmp/sr.mojo
Built: .tmp/sr.arm64  [arm64/macho]
$ ./.tmp/sr.arm64 | od -c | head -2
0000000    L   =   [ 003   ]  \n   B   =   [ 003   ]  \n   D   =   [ 001
0000020    ]  \n   l   e   n   =   3  \n
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/sr.x86_64 .tmp/sr.mojo
$ ./.tmp/sr.x86_64 | od -c | head -2        # byte-identical
0000000    L   =   [ 003   ]  \n   B   =   [ 003   ]  \n   D   =   [ 001
```

CPython on the same text, which is the whole of the finding:

```
L=[[65, 66, 67]]
B=[bytearray(b'ABC')]
D=[{'a': 1}]
```

**Both architectures agree, which is the only reason this is not a divergence
bug — and it is worse for being one wrong answer.** Exit 0, nothing on stderr,
and the single byte `003` is the blob's **count** field: a blob on this path is
`[count][element 0][element 1]…` (`formal/model.py`'s "What a value is"
section), `%s` is the one conversion that DEREFERENCES, so it walks bytes at
the operand's address until a NUL — and the low byte of the count is `3`, which
is followed by the NUL half of that word. Nothing in the container is read. For
the dict, whose count is 1, the output is `001`.

## Why it is NOT the `%d` bug, and why that distinction is the whole of this
## document

`printf("%d", xs)` is a program CPython **rejects** — `TypeError: %d format: a
real number is required, not list` — so a refusal is the honest answer and
`formal/model.py::printf_container_conversion_refusal` now gives it. This one is
the opposite: `"%s" % [65, 66, 67]` is `'[65, 66, 67]'` in CPython, the source
is correct, and the fix is an ANSWER, not a check. Putting the two in one
refusal would have been the wrong shape twice over: it would have refused
programs that work, and it would have hidden a missing feature behind a
diagnostic about a disagreement that does not exist.

`printf_arg_text_evidence`'s five steps are why nothing catches it, and each step
is right about its own case: a container operand reaches step 5, where
`kind_of(arg) == INT_KIND` is False (the kind is `list:int`), so the function
answers `None` — the permissive direction, and correctly so, because the
question that function answers is "is this operand NOT text", and a container is
not a number either. There is no row for "is this operand a container at a `%s`
" because until now the answer needed for `%s` was always "no".

## The exact next step

**One row in `formal/model.py`, beside `printf_container_conversion_refusal`
and sharing its evidence reader** (`printf_arg_container_evidence`), and the
first decision is which way it goes:

1. **REFUSE, naming the missing capability** — the safe direction, and the same
   argument `formal/model.py`'s `string_composition` refusals make: `%s` of a
   container is CPython's `repr`, this path has no `repr`, and a refusal that
   says so is better than a byte of a count field. `printf("%s", xs)` must
   still build for a `char *`, for a `bytearray` **only** if a decision says a
   byte blob's `%s` is its bytes (CPython says `bytearray(b'ABC')`, so it is NOT
   — that is a second decision, and it is why this bullet is not one line).
2. **ANSWER it**, which means a container `repr`: `[1, 2, 3]` for a list of
   numbers, `'a'` quoted for a string element, a nested container in brackets,
   `{'a': 1}` for a dict, `bytearray(b'ABC')` for a byte blob. That is a real
   emitter feature with a format table of its own and it is worth more than this
   document's subject: `print(xs)` is refused by a different sentence today
   (`print() cannot tell whether IdentExpr is a string or a number`), and the
   same `repr` answers that one properly.

**Either way the row has to be asked of `is_list_kind` and not of the
constructor's name**, for the reason the `%d` row's docstring records: a list
literal, a `bytearray()` and a `Dict` are three syntaxes and one kind, and the
element kind (`list:int` here, `list:byte` for the blob) is what says whether
there is anything to print at all.

## What a reader should be told, and the measurement that pins it

The refusal message has to name the CAPABILITY and the operand's kind, the way
`printf_container_conversion_refusal`'s names the conversion and CPython's
sentence — CPython's own words here are
`TypeError: %s must be a string, not list`, which is not much use to a reader
because it does not say what Python would have printed, and the useful sentence
is the one that says what this path CAN do instead: `len(xs)` for the count
(measured: 3, and CPython's `len([65, 66, 67])` is 3), `xs[i]` for an element,
and the `repr` the row is refusing.

## Tests

`test_formal_run.py`'s `PRINTF_CONTAINER_REFUSALS` group already carries the
`%p`, `%a`, `xs[0]` and `len(xs)` rows that bound the `%d` rule, so this one's
rows go beside them: one `refuse:` row per backend for the chosen direction
(through the existing `refuse:` runner, which requires both architectures to
print the same words), plus a guard row that `printf("%s", "hi")` still prints
`hi` — the `%s` of a `char *` is the one `%s` this path answers today and a fix
that broke it would be a much worse trade than the one it fixes.