# FORMAL_listdir_no_run_time_sequence: there is no way to return a directory listing

**Status:** open, and it is a limit rather than a defect — but it is the reason
`os.listdir` and `os.walk` are ABSENT from the `os` module rather than
approximate, and an absent function with a bug doc is a different thing from a
function that returns something plausible. Found while writing `os`; the
container capacity rule is in `formal/arm64_codegen.py` and is the same on
x86-64, so no file is claimed here.

## What I ran

```
$ cat > .tmp/pi.mojo
def count_it(parts):
    n = 0
    for x in parts:
        n = n + 1
    return n

def main(n):
    xs = ["a", "b", "c"]
    printf("n=%d\n", count_it(xs))
    return 0
$ ./.tmp/pi
n=3
```

so a `for` over a list walks it correctly. Then the same append inside a loop:

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

$ # two append SITES, two iterations: still exit 1
$ # three append SITES, three iterations: still exit 1
```

## What I saw

**A list's capacity is the number of `append` SITES in the function that builds
it, and each EXECUTION of a site counts against it.** One site, run twice,
overflows. `formal/model.py`'s `BUILTIN_VALUE_METHODS` entry for `append` says
it: *"There is no heap on this path, so the blob's capacity is a compile-time
bound — the count of append sites in the function — and the store is checked
against it."* The overflow is the Darwin `exit(1)` at
`formal/arm64_codegen.py:5252`, so it is a silent exit with no message.

So a list whose LENGTH IS ONLY KNOWN AT RUN TIME cannot be built. That is the
whole of `listdir`, and through it `walk`.

The second half is independent and just as final: even a bounded `listdir`
could not read the names. `readdir` returns a `struct dirent *` whose `d_name`
is at a fixed offset, and reading a struct on this path is a frame blob whose
word 0 is a COUNT — the same fact as
`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md`, one indirection
further out. `d_name` is a `char[256]` inside a struct the source never
declares, so there is no width to read and no offset to trust.

## What I expect, and what it is worth

`os.listdir(p)` returning the entries. Worth 12 uses across the 87 files the
sweep lists for `os`, and `os.walk` another 5, so it is not nothing — but it
is 17 of 1 400-odd measured uses, and the two things that unblock it are
Phase 6 (a real allocator) and the struct-read question, neither of which is a
patch.

## The exact next step, in the order the measurements suggest

1. **Make the overflow loud before making it rarer.** `exit(1)` with no
   message for a list that outgrew its compile-time capacity is the same
   "plausible exit, no diagnosis" shape as everything else in this family, and
   a `CodegenError`-style message naming the function, the number of append
   SITES and the capacity would turn every one of these into a named gap in the
   sweep instead of a file that exits 1. That is a one-line change in
   `_emit_list_append`'s bounds path and it helps every container, not just
   this one.
2. **Then the capacity itself.** `_blob_cap` is a fixed region
   (`_SCRATCH`, `formal/arm64_codegen.py:37`), so the honest capacity for a
   list whose length is not statically known is "the region", and the check
   should be against that rather than against the append-site count. What makes
   it not-yet-honest is that the blob is FRAME-resident, so a list of unknown
   length inside a loop is a frame that grows every iteration — which is
   FORMAL.md decision 3 and Phase 6, not a patch. Until then, refuse a
   `list` whose length is not bounded by construction, with a message that says
   which of the two reasons applies.
3. **`readdir` needs a name, not a struct.** The cheapest real answer is a
   C-level shim on the link line — `char *readdir_name(DIR *)` returning the
   `d_name` pointer — which turns the read into a `char *` this path already
   represents exactly. It needs the runtime dylib to be on a formal link line
   (`bugs/FORMAL_runtime_library_on_the_link_line.md`), so it is downstream of
   that, not parallel to it.

**What `os` does instead**, so the shape is a decision and not an omission:
`os` and `os.path` ship no `listdir` and no `walk`, and
`formal/hostmods/os/__init__.mojo` says so at the top of its
docstring. A caller who writes `os.listdir(p)` gets a
build refusal naming `listdir` — an unresolved name, with the module in hand —
which is the honest answer. The alternative, a `listdir` that returned a
fixed-capacity list of whatever fitted, would be a function whose length is a
property of the program rather than of the directory, and every caller of it
would be wrong in a way nothing downstream could detect.
