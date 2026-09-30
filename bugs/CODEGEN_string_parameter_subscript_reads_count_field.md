# `s[i]` on a `String`-annotated PARAMETER reads the blob's count field, not a byte

**Area:** CODEGEN (formal arm64 + x86-64). **Found while:** writing the
`struct` module for the formal backend (worker `mod-struct`), which needs to
read a format string character by character and takes the format as a
parameter.

**Severity: a silent wrong answer.** No refusal, no crash, no diagnostic — the
program builds, links, runs, and returns a number the source never wrote.

## What I ran

```
$ cat b1.py
def f(s: String):
    c = s[0]
    return c

def main():
    a = f("AB")
    print(a)

$ python3 fire.py build --formal --no-prove b1.py -o b1.bin
Built: b1.bin  [arm64/macho]
$ ./b1.bin
-8070450326089498624        # expected 65 ('A')
```

The same source with the string bound to a **local** in the same function is
correct, which is what makes this a bug and not a limit:

```
$ cat b2.py
def main():
    s = "AB"
    c = s[0]
    print(c)
$ ./b2.bin
65                          # correct
```

`len(s)` on the same parameter is also correct (`f(s: String): return len(s)`
returns 3), so the annotation is not being dropped wholesale — only the
subscript path misses it.

Both backends are affected. arm64 is the measurement above. x86-64 emits the
same shape (mov r10,[r11] / cmp / jl / add / cmp / ja — a count-field walk) and
returns a wrong number rather than trapping; the ELF was not executed here
because the measurement host is arm64 and no x86-64 emulator was available, so
"same wrong shape, not run" is the honest claim for that backend.

## Why

A string on this path is a bare `char *` with no header, and `s[i]` is a byte
load at `s + i`. Which path a subscript takes is decided by
`_is_string_subscript` in each backend, and that predicate consults **only** the
flow-sensitive `_string_vars` set:

```python
# formal/arm64_codegen.py:2628  (formal/x86_64_codegen.py:2777 is the same)
def _is_string_subscript(self, obj) -> bool:
    if isinstance(obj, F.StringLiteral):
        return True
    if isinstance(obj, F.IdentExpr):
        return obj.name in self._string_vars
    ...
```

`_string_vars` is populated by `_note_binding`, which only fires on a
**binding statement** whose right-hand side is a string literal (or an alias of
one). A parameter is bound by the *signature*, so it is never in the set. The
whole-function `ValueKinds` map DOES know — it is seeded from the parameter
annotations via `string_names=STRING_TYPE_NAMES` and answers `str` for `s`:

```
$ python3 -c "... M.ValueKinds(fns['g'], int_names=TYPE_NAMES,
                                 string_names=STRING_TYPE_NAMES)
             .kind_of(IdentExpr(name='s'))"
str
```

and `_expr_str_kind` (arm64_codegen.py:3122) already consults `_vkinds` as its
fallback, which is why `len(s)`, `print(s)` and `s.startswith(...)` are all
right. `_is_string_subscript` is the one predicate on this question that does
not, so the answer splits: the same name is a `char *` to three call sites and a
list blob to the fourth.

Falling through to the list path is what makes the failure silent **and**
wrong-shaped rather than a crash: a list blob is `[count:i64][elem0]…`, so
`s[0]` reads offset 0 of the pointer — the first eight CHARACTERS of the string
read as an integer — as the element count, then bounds-checks the index against
it and loads `base + 8 + 8*count`. For `"AB"` that count word is
`0x4241` and the load lands past the string. The observed value
`-8070450326089498624` is `0x9000003000000000`, a text-section address: the
walk ran off the end and read whatever the loader had mapped.

The same split exists in `dict`-subscript detection (`_is_dict_subscript`
consults `_dict_vars` only), so a `dict`-annotated parameter is exposed to the
same class of failure; I have not measured that one.

## Expected vs actual

- expected: `f("AB")[0] == 65` (the byte at offset 0)
- actual: `-8070450326089498624` on arm64, a fabricated address

## Next step

Make `_is_string_subscript` ask the same authority its siblings already ask.
The minimal, non-duplicating fix is to fall back to the whole-function map the
way `_expr_str_kind` does — in both backends:

```python
def _is_string_subscript(self, obj) -> bool:
    if isinstance(obj, F.StringLiteral):
        return True
    if isinstance(obj, F.IdentExpr) and obj.name in self._string_vars:
        return True
    if isinstance(obj, F.MemberExpr):
        key = _member_slot_key(obj)
        if key is not None and key in self._string_vars:
            return True
    return self._expr_str_kind(obj) == M.STR_KIND   # the missing line
```

`_expr_str_kind` already encodes the right precedence (`_string_vars` wins
where the two disagree), so routing through it cannot contradict the three
sites that are already correct — this is a change to one predicate, not a
second rule about what a name holds.

Two things to settle before landing it, both outside my claim area
(`module:struct`), so I have not touched either:

1. It is a change to `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`
   and therefore owes a full `make gate`.
2. Anything that currently *depends* on the wrong answer will change. The
   stdlib's `s[i]` sites on a parameter are the ones to audit; `make check` and
   the `stdlib-syntax` `U` count are the measurements that would show it.

Until it lands, a formal-path module cannot read characters out of a string
parameter. That is the constraint `struct.mojo` is written under — see the
module's own docstring, which uses `==` against a closed set of format strings
rather than indexing, precisely because indexing is not answerable here.
