# FORMAL_stat_out_parameter_is_unreadable: `isfile` cannot be exact, and `lexists` cannot exist

**Status:** open. Found while writing `os`; the blocker is that a C
out-parameter struct cannot be read on this path, which is the same fact as
`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` one level out. It is
written down because it is the reason `os.path.isfile` is a weaker test than
CPython's, and a weaker test that is not written down is indistinguishable
from a bug.

## What I ran

`stat` is the only libSystem call that answers "what kind of file is this".
There is no spelling of it that returns a value:

```
$ cat > .tmp/pc.mojo
def main(n):
    f = "/etc/hosts"
    fd = open(f, "r")
    printf("fd=%d\n", fd)
    return 0
$ ./.tmp/pc
fd=3
```

The descriptor works, and `lseek(fd, 0, SEEK_END)` on it returns the file's
size as a **value** (342 for `/etc/hosts` on this host) — which is why
`os.path.getsize` is implemented with `lseek` and not with `stat`. But the mode,
the device, the inode and the link count only ever come back through the
`struct stat` the caller supplies, and that struct cannot be read:

* it is a frame blob, so its word 0 is a COUNT
  (`formal/model.py:49-61`, `BLOB_HEADER_BYTES = 8`), and subscripting it is a
  bounds check against whatever the first field happens to hold;
* on macOS the layout has padding and the fields are not 8-byte aligned the way
  a blob's elements are — `st_dev` is 4 bytes with 4 bytes of padding before
  `st_ino`, `st_mode` is at offset 16 and `st_size` is at offset 96 — and none
  of that is stated by any source the compiler reads.

So reading a mode out of it would mean an untyped word load at a hard-coded
offset chosen by the author, and the value it produced would be a number
assembled out of adjacent bytes. That is the outcome
`formal/model.py:4139-4148` already names for `MojoList *` ("reading offset 0
… would be a plausible-looking wrong number rather than a crash").

## What it costs, precisely

| wanted | status | why |
|---|---|---|
| `exists` | exact | `access(p, F_OK)`, a value |
| `isdir` | exact | `opendir(p) != NULL`, a value; ENOTDIR for anything else, and it follows a symlink as CPython's does |
| `getsize` | exact for a regular file | `lseek(fd, 0, SEEK_END)`, a value |
| `isfile` | **weaker** | shipped as `exists(p) and not isdir(p)` |
| `lexists` | absent | needs `lstat`'s existence, which is a buffer |
| `samefile` | absent | needs `st_dev`/`st_ino` |
| `islink` | absent | needs `lstat` + `S_ISLNK` |
| `stat_result`, `chmod`-by-mode query, `access` mode bits | absent | all of it is the struct |

`isfile` is the one that ships, and the difference is real and pinned:
`os.path.isfile("/dev/null")` is **0** in CPython and **1** here. The two agree
on a regular file, on a directory, on a symlink to either, and on a path that
does not exist; they disagree on a device node, a FIFO and a socket.
`test_formal_os.py`'s `dirs` group asserts the disagreement rather than hiding
it, because a test that asserted agreement would be asserting a lie.

## The exact next step

The cheap half, and it is worth doing on its own: **a C-level shim that returns
the answer as a value.** `int is_reg(const char *)`, `int is_lnk(const char *)`,
`off_t size_of(const char *)` — three functions in the runtime, each a
`stat`/`lstat` whose answer crosses the boundary as a word. That is Phase 1's
per-arch runtime dylib (`bugs/FORMAL_runtime_library_on_the_link_line.md`), and
once the library is on a formal link line `os.path.isfile` becomes
`is_reg(p) == 1` and is CPython's answer exactly. **No change to the value
model, no struct, no field offsets** — the same move `os`'s own
`os/_syscalls.mojo` makes for every call it needs, one level further out.

The general half, for anything that genuinely needs the struct
(`stat_result`, `samefile`): that is the pointee/struct-read question in
`bugs/FORMAL_pointer_value_model.md` plus a declared layout, and it should not
be attempted before the shim, because a shim answers 90% of what a path library
is asked and does it with values this path already has.
