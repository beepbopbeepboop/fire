# FORMAL_listdir_no_run_time_sequence: a run-time-length blob is answerable; a run-time-length LIST is not

**Status: the directory half is fixed, the sequence half is open.** `os.listdir`
and `os.walk` exist in `formal/hostmods/os`, are exact, and are checked entry by
entry and in order against `os.listdir`/`os.walk` in the test process
(`test_formal_os_backing.py`'s `listdir_and_walk`, 49 answers over nine
directory shapes and three depths). What does not exist is a Python-level LIST
of a length only known at run time, and that is the part of this document's
title that is still true.

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

**A Python-level list whose length is a run-time value.** `listdir` answers
with a blob and a pair of accessors, which is honest and usable, and it is not
`xs = os.listdir(p)` followed by `for x in xs`. Four things stand between the
two, and none of them is in `formal/model.py`'s business:

1. `len(blob)` and `for x in blob` and `xs[i]` on a value this path knows is a
   `malloc`'d BLOB rather than a frame one. The blob readers all begin with
   "the base is a frame-resident blob", and nothing in the model records that a
   particular word is a heap allocation with a run-time length. The
   representation is already the same shape — that is the whole of the fix above
   — so what is missing is a KIND: `BLOB_KIND`, carried by the callee's
   declared return type, which is the same annotation channel
   `dylib_export_return_kind` already reads for `char *`.
2. A `list` LITERAL's frame reserve cannot be a run-time value
   (`_blob_est` is a compile-time upper bound), so `xs = []` followed by `n`
   appends has nowhere to put them. With (1) that becomes a `malloc`.
3. A function returning a container. `formal/model.py`'s
   "A frame that OUTLIVES the function that built it" is the shape of this: a
   frame address is not a value a caller can use after the callee returns. With
   (1) and (2) the value is a heap address, which is.
4. A `for` over it, and `len`. Both are "is this a blob" questions and both
   already exist; they need the kind from (1).

That is Phase 6's tagged-value convergence arriving from the `os` side, and it
is the same work in both directions. **It is not a patch**, which is what this
document said before, and the number in the paragraph below has not changed:
`os.listdir` is 12 uses across the 87 files the sweep lists for `os` and
`os.walk` another 5, and what is now reachable is all of them — as a blob.

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
`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` measured; the two
docstrings in `formal/hostmods/os/__init__.mojo` say what the value is and how
to read it, and a run-time-length blob with a count nobody can reach would have
been the thing not to ship.
