# FORMAL_mkdtemp_retries_a_mkdir_it_cannot_read_the_reason_for

**`formal/hostmods/tempfile.mojo`'s `mkdtemp(prefix)` draws its own name and
retries `mkdir(2)`, and the loop cannot tell a COLLISION from a FAILURE, so a
directory that cannot be made costs the whole `TMP_MAX` budget and answers
`""` where CPython raises on the first attempt.** The C library has the exact
call — `mkdtemp(3)` — and this tree now has a binding for it
(`formal/hostmods/os/_syscalls.mojo`'s `fs_mkdtemp`) that nothing calls.

Found on 2026-10-03 while merging `work/formal12-hostmods-subprocess` into
`work/merge-formal14`, where `formal/hostmods/tempfile.mojo` was an add/add
conflict: two branches had written the module from the same base. See §4 for why
master's version is the one that landed and this is not a merge defect.

## 1. What is wrong, precisely

`tempfile.mojo`'s `mkdtemp(prefix)` is CPython's algorithm with one step
removed:

```python
    var seq = 0
    while seq < TMP_MAX():
        var name = str_build(prefix, "", _name8())
        var path = join(base, name)
        if mkdir(path, 448) == 0:
            return abspath(path)
        seq = seq + 1
    return ""
```

CPython's `_mkstemp_inner` distinguishes its two `OSError` arms — `EEXIST`
retries, anything else raises. This loop cannot, because the C library's error
accessor is `__error` and **a leading underscore in a callee name is not a
symbol this image can bind** (`formal/hostmods/os/_syscalls.mojo`'s header says
so; `formal/hostmods/shutil.mojo`'s `move` is missing its cross-device
fallback for the same reason). So every `mkdir` failure is treated as a
collision.

Two consequences, both real:

* a directory that does not exist, or is not writable, spends 20 `mkdir` calls
  before answering `""`. Wrong in kind, not in value: the answer is the same
  empty string, so nothing observable is wrong except the work.
* **a collision and a failure are indistinguishable in the log too**, so a
  caller that retries on `""` cannot tell which happened. The first case above
  is partly caught earlier — `gettempdir()` answers `""` for a base that is not
  usable and `mkdtemp` returns `""` without drawing a name — but a base that
  passes `_usable` (it exists, `access(W_OK)` accepts it) and then fails
  `mkdir` is a real filesystem state: a full or read-only mount reached
  through a writable-looking path, which is exactly the one case the module
  docstring already names as the difference between `access` and CPython's
  write-and-unlink probe.

`test_formal_tempfile.py` does not catch this and cannot: it runs against a real
`/tmp` where `mkdir` succeeds, so the loop's retry path is never taken.

## 2. What already exists

`formal/hostmods/os/_syscalls.mojo`:

```
def fs_mkdtemp(tmpl) -> str:
```

It duplicates the caller's string (the C library rewrites the last six bytes,
which needs a writable buffer — a string literal here is in a read-only text
section), calls the real `mkdtemp(3)`, and returns `""` when no name could be
made. The C library does the `EEXIST` retry with the error code to itself, so
one call here is exact where a loop here can only be an approximation.

**It has no caller**, which is the whole of this bug. It landed in the same
merge, unused, and an unused binding is a capability with no evidence behind
it — the state `bugs/UNTESTED.md` is about.

## 3. Why it was not simply switched on during the merge

`tempfile.mojo` is pinned against CPython by `test_formal_tempfile.py` for four
things `mkdtemp(3)` would change:

| what | master's `mkdtemp(prefix)` | what `mkdtemp(3)` does |
|---|---|---|
| the mode | `mkdir(path, 448)` = `0o700`, asserted | `mkdtemp(3)` creates `0o700` itself (POSIX), so it agrees — but the assertion would move from the call to the platform |
| the name | `prefix` + EIGHT characters over CPython's own `characters` alphabet, asserted against this interpreter's `tempfile.characters` | substitutes SIX `X`s from the template and chooses its own characters from a different alphabet |
| the budget | `TMP_MAX` = 20, asserted against CPython's own `TMP_MAX` | the C library's own internal budget, which is not this number |
| the prefix | `gettempprefix()` = `tempfile.template`, a published export with its own test | none — the template is the caller's argument |

So switching the body is a rewrite of a merged, measured module AND its test,
across four assertions, in a commit whose job is to merge ten branches. That is
a change with its own blast radius and its own gate, not a merge decision.

## 4. The exact next step

1. Decide the signature. The corpus's 51 call sites all spell
   `mkdtemp(prefix=…)`, and a call across a dylib boundary cannot omit an
   argument (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`), so
   `mkdtemp(prefix)` has to stay one required parameter. `mkdtemp(3)` wants a
   template, so the body builds `str_build(prefix, "XXXXXX", "")` and hands
   THAT to `fs_mkdtemp` — which keeps the corpus's spelling and gets the C
   library's exactness.
2. Decide what happens to `CHARACTERS`, `TEMPLATE`, `TMP_MAX` and
   `gettempprefix`. All four are published exports with assertions against this
   interpreter's own `tempfile`, and `mkdtemp(3)` retires the first three as
   *inputs* while leaving all four as *answers*. The honest answer is that they
   stay (CPython publishes them) and only their role as `mkdtemp`'s internals
   goes away — which means `_name8` and the `mkdir` loop are deleted, not
   commented out.
3. Relax the two assertions that were about the internals rather than the
   answer: the mode (now the platform's, checked by reading the directory back
   with `os.stat`, which the module already imports) and the name's LENGTH and
   ALPHABET (still checkable as a shape — `prefix` + six characters, all of
   them from `[A-Za-z0-9]` — without pinning CPython's exact alphabet).
4. Add the case that would have caught §1: a `mkdtemp` into a base that exists
   and passes `access(W_OK)` but cannot be created in. On this host, a
   read-only directory under `$TMPDIR` is the way to ask; if the test cannot
   make one without privileges, assert the budget instead — that `mkdtemp`
   into such a base returns without drawing twenty names.
5. Then delete this doc in the same commit, per CLAUDE.md.

## 5. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_tempfile.py
```

7/7 groups pass on both architectures on the merged tree, which is the
statement that this bug is not observable through the existing suite rather
than a claim that it is absent.
