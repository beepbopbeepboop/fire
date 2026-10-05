# FORMAL_listdir_no_run_time_sequence: a run-time-length blob is answerable; a run-time-length LIST is not

**Status 2026-10-03 (`work/formal16-5`): item 1 was DONE AND HAD GONE RED ON
`master` — a newer refusal could not see the callee's own declaration, so
`names[0]` stopped building while the row that pins it was failing in the suite.
Fixed at the root (the check now asks the one reader both emitters ask), and
`test_formal_os.py`'s `os_blob_untyped_listdir`, which asserted a REFUSAL for a
declaration `listdir` no longer has, now asserts the ANSWER — the contrast with
`os_blob_untyped`, which is the same three lines through a callee whose
declaration says nothing a manifest signature can carry, is the half worth
having. Items 2 and 3 below are unchanged and remain Phase 6's tagged-value
convergence. Everything under this line is the history the document grew.**

**Status: the directory half is fixed, the sequence half is MOSTLY fixed — items
1 and 4 of "What is still missing" landed 2026-10-02 (`work/formal8-7`) and items
2 and 3 did not.** `os.listdir` and `os.walk` exist in `formal/hostmods/os`, are
exact, and are checked entry by entry and in order against `os.listdir`/`os.walk`
in the test process (`test_formal_os_backing.py`'s `listdir_and_walk`, 49 answers
over nine directory shapes and three depths). A returned blob is now a
**Python-level list** as well: `len(names)`, `names[i]` and `for x in names` all
lower, with the element kind the annotation states, and a caller's own
`triple() -> List[Int]` gets the same three. What does not exist is a list LITERAL
of a length only known at run time, and a `listdir` that has to be `free`d by hand
while a Python list is not — items 2 and 3 below, and they are Phase 6's
tagged-value convergence arriving from the `os` side.

## What landed, and what it was

The document below (kept, because its two blockers are what the fix turned on)
said that `listdir` was unanswerable for two independent reasons. Both turned
out to be things already in the tree or landed alongside, and neither needed a
patch.

**The allocator.** The claim was that a container's length must be known when
it is built, because capacity is the number of `append` SITES in the function
that builds it. That is still true of a LIST, and it is not true of an
ALLOCATION: `malloc(n)` takes a run-time size, and the memory it returns
outlives the function that asked for it, which a frame blob does not. So
`listdir` builds a blob of the shape every container on this path already has
— `[count:i64][element]…`, one word per element — in `malloc`'d memory, with the
count read out of word 0 and each element from word 1 on. Measured on
`/Users/mrs/net/chatgpt/claude/modular`: 204 entries, first, second and last
identical to `os.listdir`, in `readdir` order, which is CPython's order too.

**The struct read.** The claim was that `readdir`'s `d_name` is a `char[1024]`
inside a struct the source never declares, so there is no width to read and no
offset to trust. The offset was never the problem. A read of that struct was a
COUNT-WALK — `_emit_subscript_addr`'s blob path, bounds-checking the index
against whatever word sat at offset 0, which on a `struct dirent` is
`d_ino`. `model.subscript_base_lowering` (see below) routes a subscript whose
base has a DECLARED POIN-TEE through the pointer value model, so each byte is
now a load of the width it declares. `d_name` is at byte 21 of this target's
`struct dirent`; the whole layout, and the one byte the reading does not
account for, is written out in `formal/hostmods/os/_syscalls.mojo` and was
measured with `ctypes` on this host.

So this document's three numbered next steps read, with what happened to each:

1. **"Make the overflow loud before making it rarer."** **DONE (2026-10-01).**
   `xs.append(v)` past the append-site count used to be a Darwin `exit(1)` with
   nothing on either stream — the worst of the three answers this backend can
   give, and this document is the one that named it as "the cheapest thing
   here". It is now `model.list_append_overflow_message`, ONE text shared by
   both backends (two emitters with two copies of a sentence diverge on the
   fourth word), written to fd 2 through `write(2)` before the program stops:

   ```
   $ ./p                       # while i < 3: xs.append(7)
   formal: list.append overflowed 'xs': its capacity is 1, the number of
   append SITES in the function that built it, and every EXECUTION of a site
   counts against it — so a list built in a loop outgrows the room the frame
   reserved for it. …
   ```

   byte-identical on arm64 and x86-64, pinned by `list_append_overflow_is_loud`
   in `test_formal_run.py` (which also requires the two architectures' stderr
   to match exactly). The check stays a RUN-TIME check rather than becoming a
   refusal, because the overflow is not decidable then: one site in a
   three-iteration loop is one site and three elements, and no pass over the
   source can say it fits.

2. **"Then the capacity itself … refuse a `list` whose length is not bounded by
   construction."** NOT DONE, and the framing below is still right: the blob is
   FRAME-resident, so a list of unknown length inside a loop is a frame that
   grows every iteration. That is FORMAL.md decision 3 and Phase 6. **Step 1 is
   what makes this one safe to attempt**, which is why the document listed it
   second and called the first one "cheapest": until the overflow said which
   bound it hit, a loop-accumulating list stopped for no stated reason, and the
   count of such programs in the corpus was unknowable.
3. **`readdir` needs a name, not a struct.** DONE, and by a different route
   than the one proposed: rather than a C shim on the link line
   (`bugs/FORMAL_runtime_library_on_the_link_line.md`), the name is read out of
   the struct a byte at a time. The proposed shim would have been the only way
   *before* the byte read existed.

## What is still missing, and the exact next step

**ITEM 1 AND ITEM 4 ARE DONE (2026-10-02, `work/formal8-7`), and item 1 was a
KIND the whole time.** Measured, both architectures, for a caller's own
`triple() -> List[Int]` and for `os.listdir`:

```
var t = triple()            from tupr import triple
printf("%d\n", len(t))      ->  3          was: refused, "len() of a value
                                                classified as 'int'"
for x in t: s += x          ->  17          was: refused the same way
printf("%d\n", t[2])        ->  0           was: already worked
```

The channel was `model.imported_callee_kind` — the callee's own `-> T` read by
`declared_type_kind`, asked where the two backends' `_callee_kind` previously
asked only the manifest's C SIGNATURE. **That signature cannot answer it**, which
is why nothing had: `-> List[Int]`, `-> Int` and `-> Bool` are all `int64_t`.
Both backends call one shared function, so the two cannot answer differently, and
only a CONTAINER is taken from the declaration (an `-> Int` is deliberately not
claimed — this path cannot tell an integer from a frame address).

The element kind came with it, because item 4's two consumers both ask what the
blob HOLDS: `annotation_type_arg_base` reads `List[String]`'s argument and the
kind is `list:str`, and `ValueKinds._iterable_own_shape` reads that element off
the name a `for` walks — it returned nothing for a NAME before, so a loop target
was the model's default-for-a-word whatever the iterable held.

**For `os.listdir` the half that was missing was a DECLARATION.** It was
`def listdir(path) -> int` — a bare word — so there was nothing to read a kind
from even in unit. It is now `-> List[String]`, which is what the value has been
since the blob landed (one word pointing at `[count][element]…`), and it costs
nothing: the C signature is `int64_t` either way, so this is metadata and not an
ABI change. `walk` likewise. The three accessors REMAIN, because a caller that
wants to `listdir_free` the result has to say so.

Pinned by `test_formal_os_backing.py`'s `listdir_is_a_python_level_list` (ten
answers over two directory shapes, against `os.listdir` in this process, both
architectures) and by the `len`/`for`/subscript rows in
`test_formal_globals.py`. 54/54 in that file.

**…and that pin was RED when this round started, on `master`, on both
architectures, with 0 of its ten answers — while this document said it was
pinned.** The measurement:

    build: names[0] subscripts `names`, whose value came from `listdir` in os —
    and that export's own declaration is a POINTER (`MojoList *`), which this
    path does not carry into an unannotated local.

`formal/build.py`'s `check_subscript_through_an_unclassified_import` asks "what
does an UNTYPED local bound from this cross-image call hold?" and it asked the
MANIFEST SIGNATURE alone. The signature cannot answer it for this callee: `->
List[String]`, `-> Int` and `-> Bool` are all `int64_t` on the C side, so the
signature says `MojoList *`, the check found a pointer with no kind behind it,
and the value was refused for want of an answer the callee's own source states
in the declaration this module already reads. So the emitter lowered the
subscript through the container blob and a build-pass check refused the same
program: the two disagreed about one export, and the refusal is what a user saw.

The repair is one question asked through the reader that already exists —
`model.imported_callee_kind(entry, declaration)`, declaration first and
signature second, which is what both `_callee_kind`s use for exactly this — plus
the declarations table the check now asks for. `test_formal_os.py`'s
`os_blob_untyped` (through `re.escape`, declared `-> Pointer[UInt8]`, which the
signature genuinely cannot classify) still refuses by name on both
architectures, which is the assertion that says the check is narrower rather than
gone.

**What is still missing is items 2 and 3, and both are the same project:**

1. ~~`len(blob)` and `for x in blob` and `xs[i]` on a value this path knows is a
   `malloc`'d BLOB.~~ **DONE**, above.
2. A `list` LITERAL's frame reserve cannot be a run-time value (`_blob_est` is a
   compile-time upper bound), so `xs = []` followed by `n` appends has nowhere to
   put them. With (1) that becomes a `malloc`.
3. A function returning a container. `formal/model.py`'s "A frame that OUTLIVES
   the function that built it" is the shape of this: a frame address is not a
   value a caller can use after the callee returns. With (1) and (2) the value is
   a heap address, which is. **And this one is now measurably smaller than the
   document says it is**: the returned blob already crosses a dylib boundary and
   reads by subscript (`triple()` above) — a blob another IMAGE `malloc`s does.
   ~~What is missing is the generalisation — a container built by a LOOP and
   returned, which has no static size to `malloc`.~~ **CORRECTED 2026-10-04: a
   container returned by a function in THIS image is frame-resident too, so this
   item was not a missing capability but a wrong answer, and it is now refused
   at the read on both architectures — see the section above, and note that the
   caller-side copy landed after that section was written: a container of WORDS
   whose blob has a known size is now copied into the caller's own frame right
   after the call (`model.returned_container_blob_bytes`), so this item's
   remaining remainder is the run-time-length half below and not the
   frame-residency half.**
4. ~~A `for` over it, and `len`.~~ **DONE**, above.

That is Phase 6's tagged-value convergence arriving from the `os` side, and it
is the same work in both directions. **It is not a patch**, which is what this
document said before, and the number in the paragraph below has not changed:
`os.listdir` is 12 uses across the 87 files the sweep lists for `os` and
`os.walk` another 5, and what is now reachable is all of them — as a blob.

## 2026-10-04 (`work/formal21-5`): item 3 was not a missing capability, it was a WRONG ANSWER

**Item 3 said "what is missing is the generalisation — a container built by a
LOOP and returned", and the sentence above it said a returned container LITERAL
is `malloc`'d rather than frame-resident. Both are false, and the measurement is
the reason this document needed re-reading rather than working.**

```mojo
def lit() -> List[Int]:
    return [11, 22, 33]
def litter(n) -> Int:
    var junk = []
    junk.append(n); junk.append(n + 1); junk.append(n + 2)
    return len(junk)
def main(n) -> Int:
    var p = lit()
    printf("right after: %d %d %d\n", p[0], p[1], p[2])   # 11 22 33, both machines
    var k = litter(7)                                   # any call at all
    printf("after: %d %d %d\n", p[0], p[1], p[2])
    return 0
```

CPython answers `11 22 33` twice. This backend, before this round: `11 22 33`
and then **arm64 `7 8 9`, x86-64 `8 9 33`** — `litter`'s own scratch on one
machine and a mix of the two frames on the other, from a program that builds,
runs and exits 0. **A container is laid out in the frame by `_blob_est` in both
emitters, so NOTHING a function returns of that shape is `malloc`'d**, and the
values read correctly immediately after the call only because nothing has been
pushed over the dead region yet.

**What landed**: the escape is now REFUSED, at the read and on both
architectures (`formal/model.py::container_escape_sites`, beside the struct-frame
machinery this document's item 3 has always been the container twin of). The
check is at the read rather than at the return because the immediate read is a
shape this tree has on purpose — `formal/hostmods/struct.mojo`'s `unpack_from`
records it in its own docstring and `formal/x86_64_decode.py` uses it — and
refusing the return took that module out (measured: the hostmods census went
64/64 → 62/64 rows building). After the change the census is 64/64 again and
`test_formal_os_backing.py` is 58/58.

**The capability that would make it right is unchanged in substance and better
specified than this document had it**: a `malloc`'d blob whose length is only
known at run time (item 2) is what a copy has to copy. The COPY half of that
landed 2026-10-05 for a blob whose length IS a compile-time constant —
`formal/model.py`'s `returned_container_blob_bytes` sizes it and
`container_returned_blob_sites` gives the caller the block it is copied into —
and what is left here is exactly item 2: a blob sized by a LOOP has no constant
to size the copy with, so it is the `malloc` that has to come first. That is the
one piece of work this item still needs.

**Item 1 is unaffected** — a blob another IMAGE `malloc`s (`os.listdir`,
`os.walk`) crosses the boundary and is read by subscript today, which is the
measured 58/58.

## The original measurements, re-verified on this tree

Re-measured before the fix, on the tree this branch started from, so the two
answers are the same question asked twice:

```
$ cat > .tmp/p3.mojo
def main(n):
    xs = []
    i = 0
    while i < 3:
        xs.append("ab")
        i = i + 1
    printf("n=%d\n", len(xs))
    return 0
$ ./.tmp/p3
exit=1                 # no output
```

**A list's capacity is the number of `append` SITES in the function that builds
it, and each EXECUTION of a site counts against it.** One site, run twice,
overflows. `formal/model.py`'s `BUILTIN_VALUE_METHODS` entry for `append` says
it: *"There is no heap on this path, so the blob's capacity is a compile-time
bound — the count of append sites in the function — and the store is checked
against it."* The overflow is the Darwin `exit(1)` at
`formal/arm64_codegen.py:5252`, so it is a silent exit with no message.

So a list whose LENGTH IS ONLY KNOWN AT RUN TIME cannot be built as a list.
That is still true. What is no longer true is that this makes a directory
listing impossible: the listing does not have to be a list.

**A caveat worth keeping, because it is the shape of the wrong answer.** An
earlier version of `walk` in this branch wrote the first PATH into word 0
instead of the count, and the observable was a segfault on the first
`listdir_get` — word 0 read as a count of billions, and every read of the blob a
walk off the end of the heap. A blob's count is its own business, and nothing
about a wrong count in word 0 looks like a wrong count.

**What `os` does**, so the shape is a decision and not an omission:
`os.listdir(p)` returns a blob, `listdir_len` and `listdir_get` read it, and
`listdir_free` releases it. A caller who writes `os.listdir(p)` and then indexes
the result as a list gets the blob path's answer, which is what
`FORMAL_subscript_of_a_pointer_reads_a_blob_count` measured; the two
docstrings in `formal/hostmods/os/__init__.mojo` say what the value is and how
to read it, and a run-time-length blob with a count nobody can reach would have
been the thing not to ship.

**…and since 2026-10-02 a caller may also use the three Python spellings**, which
is what the `-> List[String]` declaration bought: `len(names)`, `names[i]` and
`for x in names`. The three accessors are still there and still the honest
spelling for a caller who frees the result, because a Python list on this path
has no `free`.
