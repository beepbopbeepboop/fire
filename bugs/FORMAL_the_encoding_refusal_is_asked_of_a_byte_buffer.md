# FORMAL_the_encoding_refusal_is_asked_of_a_byte_buffer: one non-ASCII literal anywhere in an image refuses every `Pointer[UInt8]` subscript in it, and that takes `os` — and 129 corpus files — down

**Area:** FORMAL, both backends — `formal/model.py::string_element_refusal`'s
condition, asked from the one subscript choke point each emitter has
(`formal/arm64_codegen.py:4988`, `formal/x86_64_codegen.py:4998`). **Not** the
refusal, which is correct, and **not** its image-wide condition, which is
correct for the question that condition was written for. **Status: OPEN,
measured 2026-10-05 on `work/formal27-6` at `93747a29`. Unowned** — the encoding
block landed 2026-10-04 in `f9ffd4c0` (*"formal: the encoding condition is a fact
about the IMAGE, not the MODULE"*) from `work/formal26-unicode`, which has landed
and released.

**Six rows of two registered gate jobs are red with no `expect=`, and one
host module the whole corpus reaches does not build on either architecture.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
  FAIL  a function-local import is a dependency
  FAIL  widening the imported list widens nothing else
  FAIL  a standard-library module in no tier is not reported as a typo
formal imports: PASS=69 EXPECTED=0 SKIP=0 FAIL=3

$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_admitted.py
  FAIL  ctypes
  FAIL  fcntl
  FAIL  threading
admitted contracts: PASS=20 FAIL=7 SKIP=0  (19 declared across 36 hostmod modules)
```

`test_formal_admitted.py`'s other four failures (`the Lean library's trust counts
are pinned`, `native_decide is only where decide cannot go`, `the replaced
native_decide count is what it claims`, `the census is attributed to theorems`)
are the `native_decide` ratchet — a different defect, in
`bugs/FORMAL_native_decide_axiom.md`, which is `formal27-4`'s claim. They are
named here only so nobody attributes them to this one.

## What I saw

**Every one of the six reports the same tail**, and it is not the message the
row is about:

```
build: t.mojo imports 'fcntl', which cannot be built either: _syscalls.mojo:
d[i] is refused on a string whose text is not ASCII. …
```

`d` is `formal/hostmods/os/_syscalls.mojo`'s local in `fs_dirent_name`:

```
  var d: Pointer[UInt8] = str_alloc(1024)
  i = 0
  while e[21 + i] != 0 and i < 1023:
    d[i] = e[21 + i]        # a BYTE copied out of a struct dirent
    i = i + 1
  d[i] = 0
```

so `d`'s bytes come from `readdir(3)` — arbitrary bytes, not text — and `d[i]` is
a byte store the module's own docstring calls load-bearing: *"`e` is ANNOTATED
`Pointer[UInt8]` and that annotation is load-bearing: it is what makes
`e[21 + i]` a one-byte load rather than a list-blob walk bounds-checked against
the inode number at offset 0."* That module has **31** non-ASCII string literals
(em-dashes in its docstrings, read out with the backend's own reader, below), so
the image holds a non-ASCII literal, so `string_element_refusal` fires.

### The minimal reproduction, both architectures, one em-dash

```sh
$ cat .tmp/y/with_nonascii.mojo
fn str_alloc(n) -> str:
  return malloc(n + 1)
def doc():
  """A — em-dash, so this image holds a non-ASCII literal."""
  return 0
fn copy_name(e: Pointer[UInt8]):
  var d: Pointer[UInt8] = str_alloc(1024)
  i = 0
  while e[21 + i] != 0 and i < 1023:
    d[i] = e[21 + i]
    i = i + 1
  d[i] = 0
  return d
def main():
  return doc()
```

| | arm64 | x86-64 |
|---|---|---|
| the module above | **REFUSED** `d[i] is refused on a string whose text is not ASCII` | **REFUSED**, same |
| the same module with `doc()`'s em-dash replaced by `x` | **BUILT** | **BUILT** |

That is the whole bug in two rows: **one non-ASCII literal, in a docstring, in a
function the subscript is not in, decides whether a byte store is legal.** Both
arms agree, which is what makes it a language question and not a backend
divergence.

```console
$ python3 -c "
import sys; sys.path.insert(0, '.')
import formal.model as M, formal.build as B
f = 'formal/hostmods/os/_syscalls.mojo'
print(len(M.non_ascii_strings_in(B.parse_module(open(f, encoding='utf-8').read(), f))))"
31
```

## What I expected

**A `Pointer[UInt8]` subscript is a byte, and the refusal is about characters.**
`formal/model.py::string_element_refusal`'s own docstring states the condition it
clears itself with:

> The one thing that does clear it is the condition on the whole image, which is
> the TEXT ENCODING block's argument: no literal with a byte >= 0x80 anywhere
> means no string in the image can have one, so every element read is a
> character.

That argument is sound **for a value whose bytes can only be a literal's** — and
`f9ffd4c0` strengthened it from per-module to per-image for exactly that reason
(*"a string one module interns is a value another module can hold, through a
return value or a parameter"*). It does not hold for a value whose bytes come
from a syscall, a file, or a caller. `d` is the second kind and the model cannot
tell the two apart, so it refuses the byte store.

**And it cannot tell them apart because `Pointer[UInt8]` is deliberately used for
BOTH roles in this very module** — which is why the fix is not a one-line guard
and why guessing at it would be the wrong answer:

| what the annotation is for | where |
|---|---|
| *"`Pointer[UInt8]` … tells the rest of the path this word is a **string** and not a number, and it is what `printf("%s", …)` reads"* | `str_alloc`'s docstring, `_syscalls.mojo:153` |
| *"it is what makes `e[21 + i]` a **one-byte load** rather than a list-blob walk"* | `fs_dirent_name`'s docstring, `_syscalls.mojo:1147` |
| *"`readdir(d)`: a `struct dirent *` … A `char *` and **NOT a string** on purpose"* | `fs_readdir`, same file |

So `_expr_str_kind` answering `STR_KIND` for a `Pointer[UInt8]` local is not a
bug in itself — it is what makes `printf("%s", d)` work — and the subscript
choke point has one predicate for "this subscript reads bytes out of a string"
and one refusal that asks whether the bytes are characters. **Which of the two a
given `Pointer[UInt8]` is has never been a question this tree asks.**

## Why the owning suite is green

`test_formal_unicode.py` — 96 rows, 38 in-process and 58 built on both
architectures, `PASS=96 FAIL=0` measured on this tree — is the suite that owns
this block, and every one of its rows is about `len()`, a literal fold, or the
cross-module bookkeeping. **Not one is a subscript on a buffer whose bytes come
from somewhere other than a literal.** So the condition's cost is invisible from
the inside: the rows that would catch it are rows about a shape the suite does
not exercise.

The three `test_formal_imports.py` rows are the same cause from the other side:
their fixtures (`test_runtime_header_scan.py` has 3 non-ASCII literals) hold an
em-dash, the image-wide condition fires, and the build refuses before the import
diagnosis each row is about is ever reached. That is a **fixture** problem on top
of a **refusal** problem, and fixing the fixtures alone would hide the refusal.

**And SIX MORE, in a file that could not report them** (measured 2026-10-05 on
`work/merge-formal27a-r2`):

```console
$ python3 tools/memslot.py --gb 8 --label conf -- \
      python3 test_formal_hostmods_conformance.py
FAILED  posixpath: build failed on arm64: …
FAILED  textwrap: build failed on arm64: …
FAILED  struct:   build failed on arm64: …
FAILED  shlex:    build failed on arm64: …
FAILED  re:       build failed on arm64: …
FAILED  html:     build failed on arm64: …
ok      math: 2 of CPython's own cases agree on arm64, x86_64 …
host-module conformance: 1 of 7 groups ok; FAILED: posixpath, textwrap, struct, shlex, re, html
```

All six report the same tail this doc is about — "a byte where a character
belongs is a wrong value AND a wrong one that reads plausible: for `s =
"héllo"`, `s[0]` is 104 and `s[2]` is 108" — so this is **six instances of one
defect, and it is the largest single exposure of it in the tree**: six of the
seven host modules with a CPython regression suite cannot be built at all. It was
invisible because `main()` fell off its end, so `sys.exit(main())` exited 0 with
every group red and `test_suite.py`'s `UNREGISTERED` entry could call the file
"green" on the strength of that exit code. Both are fixed on that branch (the
file returns 1 and prints the count; the entry says RED and why), so the six are
now a red an exit status carries rather than six lines in a log nobody tallies.
`re` group as its own separate defect, so `re` is two problems wearing one
group. That second defect — `re`'s scoped inline flag form `(?x: … )`, which
answered `STATUS_UNSUPPORTED` — is FIXED (`formal/hostmods/re.mojo`'s
`_p_flaggroup`), so `re` is now one problem wearing one group.

## The next step, and what NOT to do

**Do not narrow the condition back to per-module.** `f9ffd4c0` measured exactly
that: with the table replaced rather than accumulated, a two-module image where
only the first carries the accented literal printed `len=6` where CPython says
`len=5`. Per-image is right.

**Do not exclude `Pointer[UInt8]` receivers by annotation.** A `Pointer[UInt8]`
whose value holds TEXT is a character read — `formal/hostmods/str_*` returns one
and their callers subscript them — so that change converts a false refusal into
a **wrong-but-exit-0 byte answer**, which is the failure class this backend's
whole refusal set exists to prevent.

**The question that has to be answerable is: where did this value's bytes come
from?** Three answers are representable today and one is not, and the fourth is
the work:

1. **interned text** — the value is (or came from) a literal, so the image-wide
   condition is exactly the right test. `len()` and a literal fold are here.
2. **bytes from a foreign source** — `readdir`, a file read, a `memcpy`, a
   caller. There is no character obligation at all: the bytes are whatever the
   kernel said, and the right answer is the byte. `d` is here.
3. **a number** — already answered elsewhere; `_expr_str_kind` says `int`.
4. **unknown** — the honest default, and the one the fix must not turn into a
   refusal of everything: today a `Pointer[UInt8]` local is `STR_KIND`, which
   picks 1 for every one of 2, 3 and 4 alike.

A model change that carries "this value's bytes are foreign" as a kind — the
shape `formal/model.py`'s `ValueKinds` already uses for `STR_KIND`/`INT_KIND`,
seeded from a parameter's annotation and a call's return type — is the fix, and
it is one kind plus one seeding rule per site that produces foreign bytes
(`str_alloc`'s callers being the first). **It is a change to the value model on
both backends and it owes a full `make gate`; it is not a patch.**

**In the meantime, the cheap half is worth doing and is independent:** the three
`test_formal_imports.py` rows should build fixtures they own (two already write
their own, and the third builds `test_runtime_header_scan.py`, a repository file
another worker edits). That does not fix the refusal — it stops a correct refusal
from being reported as an import bug, which is the direction that costs a reader
the most time.