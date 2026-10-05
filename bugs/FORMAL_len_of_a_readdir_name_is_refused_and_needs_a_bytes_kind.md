# FORMAL_len_of_a_readdir_name_is_refused_and_needs_a_bytes_kind: the ELEMENT half of the foreign-bytes question is closed, and the `len` half is not

**Area:** FORMAL, both backends — `formal/model.py::string_codepoint_verdict`,
asked from the `len` path. **Status: OPEN, measured 2026-10-05 on
`work/gatefix11` at `cb752863`. Unowned.**

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
* The published axiom-closure table, which is `formal29-1`'s
  (`bugs/FORMAL_axiom_closure_table_is_stale_so_the_census_gate_job_is_red.md`)
  and is the one remaining failure in `formal-sweep-truth`.