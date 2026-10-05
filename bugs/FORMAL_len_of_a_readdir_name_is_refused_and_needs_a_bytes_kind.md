# FORMAL_len_of_a_readdir_name_is_refused_and_needs_a_bytes_kind: the ELEMENT half of the foreign-bytes question is closed, and the `len` half is not

**Area:** FORMAL, both backends — `formal/model.py::string_codepoint_verdict`,
asked from the `len` path. **Status: the KIND landed and the `len` half is now a
REFUSAL rather than a wrong number; the correct CHARACTER COUNT is still not
answerable. Measured 2026-10-05 on `work/gatefix11` at `cb752863`; the change
below is `work/formal31-3`, 2026-10-05.**

This is the same defect `formal/model.py::string_element_refusal`'s docstring
now records as fixed, one function over, and the sibling of the bug
`work/formal27-6` filed as `FORMAL_the_encoding_refusal_is_asked_of_a_byte_buffer`
(measured there, not fixed there either). **The element half landed** — see
"What landed" below; **the `len` half is what this document is about.**

## What I ran

```console
$ python3 tools/memslot.py --gb 4 --label ob -- python3 test_formal_os_backing.py
FAIL listdir_is_a_python_level_list [arm64]  build failed: len(x) is refused: …
FAIL listdir_is_a_python_level_list [x86_64] build failed: len(x) is refused: …
56/58 passed
```

`formal-os-backing` is in the `proofs` bucket only, which is why it is not among
the 17 gate failures on `77b24183` — it was never run.

## What I saw

The program's offending line is two, in `show()`:

```python
names = listdir(p)
chars = 0
for x in names:
    chars = chars + len(x)          # <-- refused
```

```python
$ python3 fire.py build --formal --no-prove --backend=arm64 -o x.dylib osb.mojo
build: len(x) is refused: on this path it would answer in BYTES where CPython
answers in CHARACTERS. … This image holds a string literal that is not ASCII —
'The value of the kernel string MIB `name`, or `""` if there is no such.\n\n
`sysctlbyname(name, …)` with the two-call idiom: ask once with no buffer to
learn the size, …'
```

`x` is a `readdir(3)` name. The non-ASCII literal quoted is an em-dash in
`formal/hostmods/os/_syscalls.mojo`'s `kern_str` docstring — **the same class
of cause as the element refusal: one em-dash in prose, in a function the
`len` is not in, refusing a byte-count over a kernel-supplied name.**

## Why it is not the same fix, and this is the whole of the doc

`x`'s bytes come from `readdir(3)`. There is no character obligation and no
byte obligation that the SOURCE states — a filename is whatever the kernel said,
and CPython answers `len(name)` in characters with `surrogateescape`, so the two
disagree for any non-ASCII name and agree for an ASCII one, and **this build
cannot tell which it has**.

`string_element_refusal` could be fixed by a DECLARATION because a
`Pointer[UInt8]` is a spelling that says "bytes" and the emitter already reads
the pointee for the load's WIDTH (`pointer_pointee`). `len(x)` has no such
spelling to read:

* `listdir(path) -> List[String]` — and it must: `formal/hostmods/os/
  __init__.mojo`'s own comment above that declaration is the measurement of what
  `-> int` does instead (an unannotated binding becomes an integer and
  `names[0]` answers a heap address).
* `x` is a loop TARGET, so it has no declaration of its own at all. Its kind
  comes from the container's element kind, which comes from the annotation
  above. So the only thing standing between this program and an answer is
  `String` in `List[String]`, and `String` is the honest word for a Python
  `str`.

**So the fix is a value kind for "these bytes are foreign" — the fourth
alternative `formal27-6`'s document enumerates and does not do** — or nothing.
There is no narrower one, and the two things that look narrower are both wrong:

* **Do not narrow the encoding condition.** It is per-IMAGE for a measured
  reason (`bugs/FORMAL_string_value_model.md` §"The encoding condition is a
  fact about the IMAGE, not about the MODULE"): with it per-MODULE, a two-module
  image where only the first carries the accented literal printed `len=6` where
  CPython prints 5, on both architectures, exit 0.
* **Do not exempt `List[String]` or `String`.** That is the silent-wrong-answer
  direction the block exists to prevent, and it would be wrong for every
  `String` that really does hold text — which is most of the corpus.

## What landed, and why it does not close this

`1abb8992` — `formal/model.py::receiver_is_declared_bytes`, asked by
`string_element_refusal`. **`fs_dirent_name`'s `d[i] = e[21 + i]` builds again**,
so `formal/hostmods/os/_syscalls.mojo` builds on both architectures and the six
gate rows that were red on that tail are green (`formal-ast`, `formal-os`,
`formal-shlex`, `formal-time`, plus `formal-imports`/`formal-admitted`'s rows in
the run `work/formal27-6` recorded). The corpus census is in that function's
docstring: 22 subscripts with a one-byte declared pointee, 22 in one file, 20 of
them already on the byte path.

**`len` is not reached by it and cannot be.** `string_codepoint_verdict` has no
`fn` to read a declaration from for a loop target, and the value it is asked
about has none.

## The exact next step

One kind on the value model, seeded where foreign bytes ENTER an image, and one
row in `test_formal_unicode.py`'s ORACLE table per seeding site. The seeding
sites, in the order they are worth doing:

1. **`os.listdir`'s element kind**, which is `formal/hostmods/os/__init__.mojo`'s
   `-> List[String]` and the one this row needs. Its `listdir_get(names, i) -> str`
   has the same shape and `test_formal_os_backing.py`'s 49-answer
   `listdir_and_walk` row already passes through it — so a kind here would need
   to keep that row's answers EXACTLY as they are, which is the check that says
   whether the kind was seeded correctly.
2. `os.getcwd()`, `os.getenv()` and the rest of `fs_*`'s `-> str` returns, whose
   bytes come from the kernel rather than from the image.

It is a change to the value model on both backends and it owes a full
`make gate`.

## What is NOT this document's subject

* The `Pointer[UInt8]`-declared receiver that holds TEXT and is subscripted as a
  CHARACTER read — the residual `receiver_is_declared_bytes` introduces. It is
  measured in `formal/model.py::string_element_refusal`'s docstring, its
  prevalence in this corpus is 0 of 743 files, and
  `test_formal_unicode.py`'s `byte_pointer_over_text_is_the_residual_and_reads_
  its_byte` is the row a reader can measure it with.
* The published axiom-closure table, which was `formal29-1`'s and is now
  fixed — the closure census could not see a namespace-qualified `decide` axiom,
  and `4d081b4f` is the commit that made it see one (its document is deleted
  with its fix, which is why this names the commit rather than the path). It was
  the one remaining failure in `formal-sweep-truth` when this document was
  filed.
## Status, 2026-10-05 (`formal31-3`): the kind exists, `len` is refused, and
## the wrong number is gone

**The defect was still there after the docstring wall came down, and it was a
silent wrong answer on both architectures.** Measured before the change, over a
directory holding `plain` and `héllo`:

```console
$ python3 fire.py build --formal --no-prove --backend=arm64 -o rd.arm64 rd.mojo
Built: rd.arm64  [arm64/macho]
$ ./rd.arm64
chars=11@@n=2@@                 # CPython: 10
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o rd.x86_64 rd.mojo
$ ./rd.x86_64
chars=11@@n=2@@                 # CPython: 10
```

Green build, exit 0, nothing on stderr, and the same wrong number on both
architectures — which is the shape every row of this block's "measured on both"
paragraphs has. Six for five characters is `héllo`; the sum is over the same two
names CPython sums over.

### What landed

`formal/model.py::FOREIGN_BYTES_KIND`, **a kind**, seeded where foreign bytes
ENTER an image rather than read out of a declaration — because there is nothing
in a declaration that says it. Provenance is a fact about the BODY of one host
function (`formal/hostmods/os/__init__.mojo`'s `_listdir_fill` ends in
`b[1 + n] = nm` with `nm` a `readdir(3)` result), so the seed is
`model.FOREIGN_BYTES_EXPORTS`, a table keyed on `(module identity, export name)`
— twenty-six rows over FOUR modules, every one read in that export's body:

| module | what the rows are | why it is foreign |
|---|---|---|
| `os` | `listdir`/`walk` as `list:fbytes`, `listdir_get`, `getcwd`, `getenv`, `getenv_or`, the six `environ_*` accessors, and the re-exported `fs_cwd`/`fs_getenv`/`fs_dirent_name` | `readdir(3)`, `getcwd(3)`, `getenv(3)`, `environ` |
| `glob` | `glob` as `list:fbytes` | its walk calls `listdir` |
| `tempfile` | `gettempdir`, `mkdtemp` | `getenv("TMPDIR")`/`getcwd`, and one `mkdtemp(3)` |
| `platform` | `system`, `node`, `release`, `version`, `machine`, `mac_ver_release`, `mac_ver_machine` | `uname(2)` / `sysctlbyname(3)`; `node` is a HOSTNAME, the row most likely to be non-ASCII on a real machine |

**The container spelling is what makes the element reach `len`.** `imported_callee_kind`
answers `list:fbytes` for `os.listdir` (and the seed is asked BEFORE the
declaration, because `-> List[String]` is the honest word for a Python-level list
of `str` and CPython agrees with it), `list_elem_kind` carries the element
through the container axis exactly as it does for `list:str`, and a `for x in
names` loop target — which has no declaration of its own — is the only channel
there is. That is why this could not be done by annotating the host module's
return type: `List[Bytes]` would be a claim about the type, and the type is
`List[str]` in CPython too.

**`len` is refused, by name, and the refusal says where the bytes came from.**
`len_operand_lowering` answers `None` for the kind (deliberately `== STR_KIND`
there and `string_operand_is_string` everywhere else — the docstring says why,
and the difference is the whole of the change), and `len_refusal` grows a row
that quotes the measurement, says the declaration is `-> List[String]` and is
honest, and then says what the caller CAN do: `==`, `in`, `startswith`,
`printf("%s", …)` and `print` are all properties of the BYTES and CPython agrees
on every one of them (`os.listdir` decodes with `surrogateescape` and writes the
same bytes back out), and `os.str_len(x)` is the `strlen` on purpose.

### What is NOT claimed, and it is two things

1. **The CHARACTER COUNT is still not answerable, so `len` over a kernel string
   is refused rather than right.** It is the safe direction and it costs a real
   capability: `len(getcwd())` used to answer, and it answered correctly for
   every ASCII path and wrongly for every other one. Answering it needs a
   code-point count over bytes at run time — a loop this path's expression
   lowerings cannot emit — and CPython's is `surrogateescape`'s, which is
   maximal-subpart splitting: `b"\x80"` is one character and a lead byte with a
   truncated sequence is one surrogate per byte, so "count the bytes that are not
   continuation bytes" is wrong for both and is not the cheap version of the
   right answer. **This is the next piece of work and it is not small.**
2. **A COMPOSITION does not carry the kind, and `os.path` is where that shows.**
   `os.path.join(getcwd(), p)` is a host-side `malloc` of the caller's bytes and
   a kernel's, and the kind of a result is the kind of its arguments, which this
   path does not track — so `len(os.path.abspath(p))` and
   `len(os.path.realpath(p))` still answer in bytes. The same applies to
   `platform.platform`, `platform.platform_string` and
   `platform.system_alias_*`, whose `_alias_part` picks one of three arguments.
   All of these are deliberately absent from the table and
   `foreign_bytes_export_kind`'s docstring says so with the reason, because a
   row for them would refuse `len` over a string the caller can see every byte
   of — the direction this kind exists to avoid.

### The tests, and what each row can fail on

`test_formal_unicode.py`'s model section gains **21 rows** in five groups, in
the order of the decisions rather than of the table: the seed (one row per KERNEL
SOURCE plus one per EXCLUSION — `os.sep`, `glob.escape`, `gettempprefix`,
`architecture_bits` — because the exclusions are as much a part of the answer as
the rows), the `len` refusal and its message, everything that must stay unchanged
(`len` of a `str` is still a `strlen`, a subscript is still one byte, truthiness
is emptiness, `is_number_kind` says no), the element axis, and the ORDER (the
seed wins over the declaration; an unseeded export still answers from its
declaration). **84 model + 147 behavioural checks, all PASS.**

`test_formal_os_backing.py` gains a **separate non-ASCII fixture**
(`@@UTF8@@`, and a separate directory on purpose — `listdir_and_walk` walks
`@@ROOT@@` recursively against a CPython oracle, so two more entries there would
change its 49 answers for a change that has nothing to do with them) and **five
rows × both architectures**: the `len(x)` refusal, the CONTROL that prints the
name and measures it in bytes with `os.str_len` against an `os.fsencode` oracle,
the `getenv` refusal, the `getenv` value still printing, the `getcwd` refusal,
and a `glob` + `platform.node` refusal so the seed is shown to reach a second
dylib. **`listdir_is_a_python_level_list`'s aggregate changed from `chars` to
`bytes`** — `os.str_len(x)` summed, against `len(os.fsencode(x))` — because
`len(x)` is now refused, and its other five answers are unchanged, which is what
says the seed landed at the element and nowhere else. **68/68, and 58/58 before.**

`test_formal_run.py` is **1043/1043** and `test_formal_value_model.py` **83/83**,
which is the check that matters for a change that rewrote nine `== STR_KIND`
comparisons: every one of them now reads `string_operand_is_string`, which
returns the same answer for every kind that existed before this one.
