# FORMAL_glob_copy_collections_io_not_attempted: `glob`, `copy` and `collections`, re-measured 2026-09-30

**Status: NOT WORK, and closed 2026-10-01. Nothing here is module-shaped, and
the one recommendation that was still outstanding has been carried out.**

Every remaining action this document names is one of three things, and all three
are now settled rather than open:

* `glob` — the "ship the pattern half alone" advice is **WITHDRAWN** above, with
  the measurement that withdrew it. `glob.glob` returns a run-time-length list,
  which `bugs/FORMAL_listdir_no_run_time_sequence.md` already decomposes, so a
  real `glob` is blocked on a capability and not on a module.
* `collections` and `copy` — the recommendation was "one bug doc for `clone` +
  a constructible type, covering `copy` AND `collections` together … That doc
  does not exist yet and should". **It exists now**:
  `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`, which
  re-measures the five files on this tree (all five still stop at the host
  import, so a module would convert 0), decomposes the capability into a
  compile-time-known record / a shallow struct clone / a runtime reflection
  table, and folds in the copy-construction half that
  `FORMAL_frame_receiver_handoff.md` §4c already names as missing.
* `io` — closed above, and it has been since 2026-09-30.

**What a reader should take from this instead of the doc.** The rule it
restates is still the rule and is still the answer for any of these three
modules: *a value cannot cross a dylib boundary unless it is one 64-bit word.*
`glob.glob`, `collections.Counter` and `copy.deepcopy` are all "hand back a
list / a dict / a new object", so all three are that one sentence before they
are anything module-specific, and writing any of them converts **zero** files
until the capability lands. The measurements below are kept because they are
what establishes that, and they are re-derivable in about a minute with the
stub-module trick they describe.

> **RE-MEASURED 2026-10-01 — the numbers in `glob` and `collections` below are
> STALE and the recommendation they end on has changed. Read
> `bugs/FORMAL_platform_reachable_row_measured.md` §3 and §4 first.**
>
> What is still true: none of the three was written, for the reasons given, and
> `collections` is worth **zero** files — which was measured again, by stub, and
> again comes out zero.
>
> What is now false, and both corrections change what to do next:
>
>  * **`collections`: "three of the four are waiting on `re`" is wrong.** `re`
>    landed. Re-stubbed on 2026-10-01, all five files (the count was 4 here, 5
>    in the 2026-10-01 sweep) walk PAST `re` and land on `shutil`,
>    `subprocess`, `concurrent.futures` and `importlib.util` — all permanent.
>  * **`glob`: "blocked on `os.listdir`, not on `glob`" is wrong.**
>    `formal/hostmods/os/__init__.mojo` now has `listdir` and `walk` as exact
>    run-time blobs, so the listing is available and is no longer the blocker.
>    §`glob`'s "the remaining work is `has_magic` and `escape` — a day's worth —
>    plus the listing, which is Phase 6" is therefore an over-estimate of what is
>    left and an under-estimate of what is hard: the listing is done, and what
>    remains is the pattern walk and `**`.
>
> The old §`glob` advice to ship the pattern half alone is **withdrawn**: with a
> stub `glob` on the search root, 9 files convert from "out of reach, with an
> owner" into "refused by the export map", which is a fact about the target
> dressed as a gap in the backend. `bugs/FORMAL_platform_reachable_row_measured.md`
> §3 has the nine-file table and what a real `glob` is worth (5 files to
> permanent, 4 into real codegen findings, 0 to PASS).

Re-measured on this tree (2026-09-30, the `module:copy+collections+io+json+
pathlib+typing+builtins` claim) with `python3 tools/formal_sweep.py` on each
terminal file, so every number below is from a run and not from the 2026-09-29
text this replaces. That text was a scope record written before `json`,
`pathlib`, `io` and `typing` were written, and it got three of its four
recommendations wrong: `io.open` is not writable, `io` did not unblock the
one file that wanted it, and the "order I would take them in" is the wrong
order because two of the three remaining modules are downstream of other
workers' claims.

What landed from the same claim, and where it is written down:
`formal/hostmods/json.mojo` (`test_formal_json.py`),
`formal/hostmods/pathlib.mojo` (`test_formal_pathlib.py`),
`formal/hostmods/io.mojo` and `formal/hostmods/typing.mojo`
(`test_formal_small_hosts.py`).

---

## The rule that decides all three, restated because it is the whole answer

**A value cannot cross a dylib boundary unless it is one 64-bit word**
(`formal/hostmods/sys.mojo`, `bugs/FORMAL_module_state_no_storage.md`). A list
is a frame blob carved out of the caller's frame; a dict is the same; a tuple is
the same. All three of these modules exist to hand back exactly such a value,
and none of them has a spelling that is a word.

---

## `collections` — 4 files, and NONE of them reaches the wanted name

`formal/lean.py:816`, `formal/model.py:7209`, `tools/arm64_insn_audit.py:94`
and `tools/formal_sweep.py:1580,1620` want:

```python
Census = collections.namedtuple("Census", "ok detail cached n_sorries …")
counts = collections.Counter()
```

**`namedtuple` constructs a TYPE** — a new class with N fields, an `__init__`,
`__repr__`, `_asdict`, iteration and indexing. On this path a type is not a
value, so it cannot be returned from a module function, let alone stored in a
module-level name; and `Census(...)` at the use site would then be a call to a
name the compiler has no declaration for, which is
`bugs/FORMAL_from_import_alias_dangles_the_call.md`. **`Counter` is a dict**,
which is the blob above.

**What I measured, and it is not what the 2026-09-29 text said.** With a stub
`formal/hostmods/collections.mojo` on the search root — one function, no
`namedtuple` — every one of the four files moves to a DIFFERENT host import and
none of them reaches the `namedtuple` call:

| file | with `collections` resolved, it fails on |
|---|---|
| `formal/lean.py` | `re` (mod-re's claim, in flight) |
| `formal/model.py` | `re` |
| `tools/arm64_insn_audit.py` | `re` |
| `tools/formal_sweep.py` | `concurrent.futures` (permanent) |

and a program whose only problem is the call is refused by the export map:

```
build: collections.namedtuple(): `collections` is a linked module but it
exports no `namedtuple`, so the call has no symbol to bind. What it does
export: …
```

So the module is not the next obstacle for any of the four, and **writing it
would move zero files** — the honest number, and the reason this is a record
rather than a task. Three of the four are waiting on `re`, which is a real
module and is being written; the fourth is waiting on a second process.

**What would actually close it** is a type crossing a boundary, which is a
compiler capability. `doc/ABI.md`'s "Aggregates" section already says structs
are passed by pointer with a reflection-table layout; extending that to
*constructing* a type at run time is the real work, and whoever does it will
want to know that `copy` needs the same thing (below) — which is why the
2026-09-29 advice to do them as ONE piece rather than two module-shaped ones
was right and is repeated here.

## `copy` — 1 file, and it is DOWNSTREAM of another worker's claim

`mojo/middle/coro.py:1484` wants `copy.copy(call)` and `mojo/middle/coro.py:4012`
wants `copy.deepcopy(node)`, where `call` and `node` are AST nodes.

`copy.deepcopy` is a **generic walk over an arbitrary object graph**: read every
attribute, decide which are values and which are references, allocate a new
object per node, repoint the edges. Every step is a capability this target does
not have, and they are not one capability: an object with a type tag and
readable attributes exists (the gimple runtime carries one and
`mojo_obj_getattr` reads it), so the READ half is reachable; allocating a new
instance of an ARBITRARY TYPE is not; discovering the attribute set of a type
at run time is not; and knowing which attributes are edges and which are
scalars is not, and guessing gives a copy that shares structure it should not.

So `copy` on this target would be `copy.copy(x) -> x` for a scalar and nothing
else, which is a function whose name promises a graph walk and delivers an
identity. That is the same shape as a wrong `time.time()` and
`bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md` filed a decision rather than
shipping one.

**Measured, and it changes the priority.** With a stub `copy.mojo` on the
search root, `mojo/middle/coro.py` does not reach the `copy` call at all — it
moves to `dataclasses`, which is `merge2-formal`'s claim and is in flight. So
`copy` is not even the next obstacle for the one file that wants it, and a
program whose only problem is the call is refused by the export map:

```
build: copy.copy(): `copy` is a linked module but it exports no `copy`, so the
call has no symbol to bind. What it does export: …
```

**What would actually unblock `coro.py`** is a `clone` capability in the
backend — a new node with the same type and freshly-allocated fields. That doc
does not exist yet and should; it is the same capability `collections` needs
(see above) and the two should be filed as ONE bug, because whoever writes it
will hit both and a reader who finds one should be told about the other.

## `builtins` — 0 files, and it is a MODULE-ATTRIBUTE question

Four files import it — `tools/codeindex.py:19`, `tools/extract_family.py:15`,
`tools/wave2b_fix_deps.py:181` and `tools/wave2c_explicit_imports.py:18` — and
all four are refused earlier for `ast`, which is `merge2-formal`'s claim. So
`builtins` unblocks **nothing** today, and the sweep reports zero files for it.

The four uses are one line each: `set(dir(builtins))`, to seed a free-variable
scan. And `dir(builtins)` is not an export problem at all — measured, with a
stub `builtins.mojo` on the search root:

```
build: main: 'builtins' is imported from `builtins`, so it is a module-level
name of another module. This path compiles an import into a dylib, and a
module-level name is not exported as a word — there is no storage for it here…
```

So the obstacle is **module-attribute access**, which is a compiler capability
and not this claim's: it is `construct:module-attribute-access`, held by
another worker, and `bugs/FORMAL_module_state_no_storage.md` is the storage
half. A `builtins` module of FUNCTIONS would not help, because the four files
want the module's NAMES, not a function.

## `io` — CLOSED, and the 2026-09-29 recommendation does not work

The old text said the writable part was "`io.open` as a thin wrapper over the
`os` module's `open`/`lseek`/`close` (which exist and are tested), and the
buffer constants", and put it second on the list. **Both halves are wrong, and
the first is wrong in a way that was checkable by reading a file.**

`formal/hostmods/os/_syscalls.mojo` has `fs_open_ro`, `fs_lseek`, `fs_close` and
**no read and no write call**. A wrapper over those opens and seeks and cannot
read a byte, and a file's CONTENTS are the whole point of `io.open`. So there is
no `io.open` here, and `formal/hostmods/io.mojo` is the constants instead:
`SEEK_SET`, `SEEK_CUR`, `SEEK_END` and `DEFAULT_BUFFER_SIZE`, each checked
against CPython's own `io` by `test_formal_small_hosts.py`.

`io.StringIO` is a growable buffer with a cursor. A buffer that grows is a
run-time-length sequence — a list's capacity is the number of `append` SITES in
the function that builds it — which is the same limit that stops `os.listdir`
and SHAKE (`bugs/FORMAL_listdir_no_run_time_sequence.md`).

**And the one file that wanted `io` still does not build**, which the old text
promised it would:

```
before: test_formal_sweep_truth.py imports 'io', which is a host module …
after:  test_formal_sweep_truth.py imports 'unittest', which is a host module …
```

It wanted `io.StringIO()` for a `redirect_stderr` capture and now names
`unittest` first, which is permanent. So `io` moved that file OFF the
host-import class and unblocked nothing — the same honest accounting as
`collections` above, and the reason the claim's real yield was `json` (6 files)
and `pathlib` (2), not the small hosts.

## `glob` — unchanged, and still the best of the four

The old text's section on `glob` still holds and is not re-measured here
because `glob` is not in this claim: 4 files want it
(`formal/x86_64_model_test.py`, `test_examples_parse.py`,
`test_no_new_container_casts.py` and `test_relaxed_imports.mojo`), all four
spelling `sorted(glob.glob(os.path.join(REPO, "*.py")))`, and `glob.glob`
returns a list. `glob` is blocked on `os.listdir`, not on `glob`
(`bugs/FORMAL_listdir_no_run_time_sequence.md`): a directory listing is both a
run-time-length sequence and a `struct dirent` whose field offsets the source
never states.

What IS writable is the pattern half — `has_magic`, `escape`, and
`match(name, pattern) -> int` — and `formal/hostmods/pathlib.mojo` now contains
the `fnmatch` matching that `glob`'s pattern half needs, as
`pathlib.match(path, pattern)`, with the two rules `glob`'s own matcher adds on
top (a leading `/` anchors, and matching is right-aligned) implemented and
checked against CPython's `PurePath.match` over 56 pairs. So `glob`'s pattern
half is closer than it was, and the remaining work is `has_magic` and `escape`
— a day's worth — plus the listing, which is Phase 6.

## The order I would take them in, in light of the measurements

Different from the 2026-09-29 list, and each item says what it is worth:

1. **`glob`'s pattern half** (`has_magic`, `escape`), reusing
   `pathlib.match`. Moves 4 files to a codegen refusal naming `os.listdir`.
   Half a day. Still the best of the four.

   **WITHDRAWN 2026-10-01.** `os.listdir` landed, so the listing is not the
   blocker any more; and shipping `glob` without `glob.glob` converts 9 files
   from a reachable gap into an export-map refusal, which is the wrong label
   for a fact about the target. See
   `bugs/FORMAL_platform_reachable_row_measured.md` §3 for the measurement and
   for what a real `glob` is worth.
2. **One bug doc for `clone` + a constructible type**, covering `copy` AND
   `collections` together. Zero files, but it is the root cause of two of the
   three and the two are the same capability. Not a module-shaped piece of work
   and should not be attempted as one.
3. **Nothing for `builtins` until `ast` lands** — it is a module-attribute
   question, and `construct:module-attribute-access` owns it. When `ast` lands,
   re-measure: if the four files then fail on `builtins`, the answer is still
   the module-attribute capability and still not a module.
