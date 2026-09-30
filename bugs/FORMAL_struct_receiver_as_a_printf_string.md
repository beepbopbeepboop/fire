# FORMAL_struct_receiver_as_a_printf_string: printing a struct SEGVFAULTS, on both architectures

**Status: OPEN, pre-existing, and NOT specific to `@dataclass` — found while
proving that `@dataclass`'s generated `__repr__` has no representation here.**
A struct receiver passed to `printf` with a `%s` conversion, or to `str()`, exits
139. That is a crash, so it is not a wrong answer, but it is the reason
`@dataclass` cannot be said to work: `repr=True` is the DEFAULT and it
generates a `__repr__` the source then relies on.

Found while writing the `dataclasses` transform for the formal backend
(2026-09-29, the `module:dataclasses` claim). Every measurement is from this
tree.

---

## What I ran

```python
class C:
    x: int
    y: int

def main(n):
    c = C(1, 2)
    printf("%s\n", c)      # and, separately: str(c)
    return 0
```

```console
$ python3 fire.py build --formal --no-prove -o r1 r1.py && ./r1
Built: r1  [arm64/macho]
Segmentation fault: 11
$ echo $?
139
```

Both spellings, and both of them. A one-field struct too, so it is not about
the frame: `struct_is_framed` is `False` for one field and the receiver IS the
field, and it still crashes.

## Why it happens, as far as it is diagnosed here

A struct of more than one field is lowered as a POINTER to a frame of 8-byte
slots (`formal/model.py`'s `struct_is_framed`), and a one-field struct's
receiver is the field's own word. Neither carries anything saying "this is
text". `printf` with a `%s` conversion reads bytes at the address it is handed
until it finds a NUL — and the thing at that address is a frame of small
integers and other frames' addresses, none of which is a NUL-terminated string
in any predictable place. So it walks off the end of the frame and faults.

That is the same reasoning as `formal/model.py`'s `frame_receiver_escape_refusal`
("a `char *` is a pointer to text and every `%s` DEREFERENCES it"), applied to
the `printf` builtin rather than to a call. **The refusal exists for a callee
and does not fire for a C library variadic**, and the reason is visible in the
corpus: `printf` takes a variable number of arguments, so there is no parameter
list for the escape check to walk the arguments against.

`test_formal_os.py:62` already notes the neighbouring half of this ("`printf`
… as an integer, which is what a predicate has to be compared as"), so the
`%d`-of-a-struct case is handled somewhere and the `%s` case is not.

## Why it is filed rather than fixed here

Two reasons, and the first is the claim.

1. **It is not a dataclasses construct.** It is a `printf` conversion on a
   struct receiver, and it reproduces with no `@dataclass` anywhere in the
   program. `formal/arm64_codegen.py`'s variadic emission and the conversion
   dispatch are outside the `module:dataclasses` claim.
2. **The fix is a refusal, and refusals for this shape live in `formal/model.py`
   beside the others** — `string_operand_is_string` and
   `frame_receiver_escape_refusal` — which is also outside the claim.

So `formal/dataclass_transform.py` refuses `@dataclass(repr=…)` with a message
that NAMES this gap rather than papering over it, and that message is the only
thing in this tree that points a reader at it.

## What would close it

**Refuse it, in the same place the string-operand refusals already live.** A
`%s`-or-`%r` conversion whose argument is a struct receiver has no
representation — the value is a frame address and the conversion wants text —
and the honest answer is the same one every other string/refusal in
`formal/model.py` gives. Concretely:

* in `formal/model.py`, a `printf`-family refusal beside
  `string_operand_is_string`, reading the same kind table, so the message
  names the conversion and the receiver the way `str + str` names its operands;
* the arm64 and x86-64 emitters ask it from where they already handle the
  builtin, and the refusal is arch-free text so one case pins both;
* `test_formal_run.py` gains a `refuse:` case, and the current behaviour — a
  clean SIGSEGV at run time, with the build green — becomes a build error.

**Cost: under an hour, and it is a one-word fix at every site that turns a
139 into a diagnostic.** It is worth doing on its own merits: today this
failure mode is "the program builds, links, runs, and dies", which is the class
of defect this backend's whole refusal discipline exists to convert into a
message.

## The dataclasses consequence, stated so it is not lost

`@dataclass`'s `repr=True` is the DEFAULT and generates `__repr__` as
`C(x=1)`. That is not the inherited `object.__repr__` a bare class would
otherwise reach, so it cannot be waved through as "the same as a bare class" —
even though a bare class has the same crash. So `repr=True` is refused
(measured message: "`@dataclass(repr=…)` is not lowerable on this path …
printing a struct receiver SEGFAULTS on both architectures today"), and
`repr=False` is refused for the same reason rather than offered as a way
around it. Both are pinned by `test_dataclasses_formal.py`.
