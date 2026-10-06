# A bare C `int` return with no `BARE_C_RETURN_KINDS` row is not sign-extended, so every operation on it is wrong

**Area:** FORMAL, the bare-extern return convention. **Status: OPEN, measured
2026-10-05 on `work/formal37-2` at `94655b4e`. Unowned, and NOT this branch's
lane** — found while landing the `printf("%d")` widening
(`formal/model.py::printf_widened_format`, `94655b4e`) and deliberately NOT
fixed there, for the reason §"Why the printf fix did not close it" gives. Every
number below was measured on both architectures.

## What I ran

```console
$ cat .tmp/pd/haz3.mojo
def main(n):
    var a = strcasecmp("a", "b")
    printf("sc_d=%d lld=%lld u=%llu raw=%lx\n", a, a, a, a)
    return 0

$ python3 tools/memslot.py --gb 8 --label h -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/pd/h .tmp/pd/haz3.mojo
Built: .tmp/pd/h  [arm64/macho]
$ .tmp/pd/h
sc_d=-1 lld=4294967295 u=4294967295 raw=ffffffff
# x86_64: byte-identical
```

and the C control, which is what the word is supposed to be:

```console
$ cat .tmp/pd/h3.c
#include <stdio.h>
#include <strings.h>
int main(void){ int a = strcasecmp("a","b");
  printf("d=%d lld=%lld\n", a, (long long)a); return 0; }
$ clang -O0 -o .tmp/pd/h3a .tmp/pd/h3.c && .tmp/pd/h3a
d=-1 lld=-1
$ clang -O0 -arch x86_64 -o .tmp/pd/h3x .tmp/pd/h3.c && .tmp/pd/h3x
d=-1 lld=-1
```

The image's `%lld` answers **4294967295** where C's answers **-1**, and
`raw=%lx` says why: the word in the register is `0x0000_0000_FFFF_FFFF`.

## What I expected

`strcasecmp` returns C's `int`. `strcmp`, `memcmp` and `atoi` return C's `int`
too, and this path gets all three right — measured, both architectures:

| | `%d` | `%lld` |
|---|---|---|
| `strcmp("a","b")` | -1 | -1 |
| `memcmp("a","b",1)` | -1 | -1 |
| `atoi("-2147483648")` | -2147483648 | -2147483648 |
| **`strcasecmp("a","b")`** | **4294967295** | **4294967295** |

## What it is

`formal/model.py`'s `BARE_C_RETURN_KINDS` is this path's answer to AAPCS64 §6.9
/ SysV AMD64 §3.2.3 — "a value smaller than 8 bytes is returned in the least
significant bits, the remaining bits are unspecified" — and
`bare_c_return_kind` applies the `(32, True)` row as a `sign-extend` in both
emitters' `_emit_extern_return`. **`strcasecmp` is not in the table**, so
`bare_c_return_kind` answers `None`, and `None` means "the callee's return width
is not established anywhere, so the register is handed on as it arrived"
(`_emit_extern_return`'s own docstring). What arrived is zero-extended, because
a W-register write on AArch64 and a 32-bit write on SysV both zero the upper
half — and `test_formal_libc_symbol.py`'s `retkind` group says exactly this in
its header comment, quoting the measurement that found the table.

**So the defect is not `printf`.** It is that the model's value for that word is
wrong, and `printf` was the one rendering that accidentally agreed with C:

| operation on `strcasecmp("a","b")` | this path | C |
|---|---|---|
| `printf("%lld", a)` / `print(a)` | 4294967295 | -1 |
| `printf("%d", a)` | -1 | -1 |
| `a < 0` | **no** | **yes** |
| `a + 1` printed through `%d` | **0** | 0 |

`a < 0` is the row that matters and it is the one nobody had: a comparison on a
libc `int` return is a **silent wrong boolean** on both architectures, and it is
invisible to any test whose subject is an arithmetic expression.

## Why the printf fix did not close it

`model.printf_widened_format` widens `%d` to `%lld`, which for this word
CHANGES a right answer into a wrong one — measured, before and after:

| | before | after the widening |
|---|---|---|
| `printf("%d", a)` | -1 | 4294967295 |

That is the whole argument for the direction taken and it is worth stating
plainly, because it is a real cost and not a free lunch: the widening was landed
**anyway**, because `print(a)` already answered 4294967295 and `a < 0` already
answered `no`. The word this path holds for that value IS 4294967295, and
widening `%d` makes the last rendering agree with the rest of the model instead
of leaving one that contradicts it. **The defect this doc describes is
upstream of `printf` and is what makes the whole row wrong.**

## The exposure, measured, which is why this is filed rather than fixed

`BARE_C_RETURN_KINDS` is total over `formal/hostmods/` and that totality is
pinned: `test_formal_libc_symbol.py`'s `retkind` group asserts every bare callee
the host modules make is either in the table or in `HOSTMOD_NON_C_CALLEES`, and
asserts backward that every table entry names a symbol the host C library
defines. A broader walk of the same shape, over this repository's own `.mojo`
files plus the stdlib — 423 files, 840 distinct bare callees, 121 of them real
libc symbols found with `ctypes.CDLL(None)` — finds:

> **every real libc bare callee has a `BARE_C_RETURN_KINDS` row. Zero
> exceptions.** And of the 18 `printf` varargs over those same files, **zero** is
> a bare call without one.

So nothing in this corpus can observe the defect. That is a fact about the
corpus, not a defence of the table: a program *outside* the host modules can
name a libc `int` return itself, which is exactly what the reproducer does, and
`formal/model.py` has no way to tell that name from a Mojo one at the `BL`.

## The exact next step

1. **Decide the rule, because "add every libc `int` return" is not it.** The
   table is currently a list somebody maintains on purpose, and its backward
   check asks the C library whether each name is real — which is what makes a
   typo visible. The alternative worth arguing is a POSITIVE rule: a bare
   callee that is a **libc** symbol (`ctypes`/`dlsym`-style lookup at import
   time, or a generated header) and has no row is refused by name, on the
   grounds that an unnormalized `-1` is a wrong boolean rather than a missing
   diagnostic. That is a refusal, so it trades a wrong answer for a build
   failure — which is this codebase's direction everywhere else, but it needs
   the export exception re-checked, because `basename`/`dirname`/`str_copy` are
   real libc names bound to this project's own functions.
2. **Pin the mechanism either way** with a build-and-run row beside
   `test_formal_libc_symbol.py`'s `retvalue` group: `strcmp("a","b")` and
   `strcasecmp("a","b")` in one program, asserting the first is `-1` and the
   second is **refused** (option 1) or `-1` (option "add the row"). The row has
   to name BOTH names, because a suite with only the working one passes today
   and would keep passing with the table unchanged.
3. **Then, separately**, re-check whether `printf`'s widening is still the right
   answer for whatever option 1 decides — it is written up on the premise that
   the model holds one 64-bit value per word, which option 1 does not change.

Reproducing the measurement needs nothing but a `printf` program and
`fire.py build --formal`; the census of §"The exposure" is the `strcasecmp` row
plus `test_formal_libc_symbol.py`'s existing `retkind` group, which is where a
new name has to be registered.