# FORMAL_glob_copy_collections_io_not_attempted: the four remaining claimed modules, and why each is blocked before any code

**Status: OPEN, and this is a SCOPE RECORD rather than four bug reports. It
says what `module:glob+copy+collections+io` actually is on this target, so
nobody picks one of them up expecting a day's work and finds a week.** Written
2026-09-29 at the end of the `module:small-hosts` claim, having landed `time`
and `hashlib` from the same claim.

The rule this tree already states, and which decided all four: **a value
cannot cross a dylib boundary unless it is one 64-bit word**
(`formal/hostmods/sys.mojo`, `bugs/FORMAL_module_state_no_storage.md`). A
list is a frame blob carved out of the caller's frame; a dict is the same; a
tuple is the same. Every one of these four modules exists to hand back
exactly such a value. That is not a hard part of the work — it is the first
question, and it has the same answer for all four.

---

## `glob` — 4 files in the sweep, and the count is misleading

`formal/x86_64_model_test.py`, `test_examples_parse.py`,
`test_no_new_container_casts.py` and `test_relaxed_imports.mojo` are the four
files, and all four spell it the same way:

```python
for path in sorted(glob.glob(os.path.join(REPO, "*.py"))):
```

**What `glob` has to return is a list, so this module cannot be written as
CPython spells it** — and that is the smaller of the two obstacles. The larger
one is underneath it:

* `glob()` enumerates a directory, and `os.listdir` cannot exist here for two
  independent measured reasons, both recorded in
  `bugs/FORMAL_listdir_no_run_time_sequence.md`: a list's capacity is the
  number of `append` SITES in the function that builds it, so a list whose
  length is only known at run time cannot be built at all; and `readdir`
  reports a name in a `struct dirent` whose field offsets the source never
  states, which is a frame blob whose word 0 is a count.

So `glob` is blocked on `listdir`, not on glob. Writing a glob whose listing
returns nothing would move four files from `not-answerable/host-import` to a
codegen refusal naming the real obstacle — which is what the sweep calls
progress — and that is worth doing eventually, but the four files still would
not build.

**What IS writable and useful in the meantime**, if someone wants the four
files to move: the pattern half. `has_magic(pattern)`, `escape(name)`, and a
`match(name, pattern) -> int` that is a real fnmatch translation with `*`,
`?`, `[seq]`, `[!seq]` and `**`. All pure string-to-string or string-to-int,
all testable against CPython's `fnmatch` the way `test_formal_os.py` tests
`posixpath`. That is a real module and it is about a third of what CPython's
`glob` is; what it cannot do is enumerate, and the module would say so at the
top.

## `copy` — 1 file, and the capability is not a module

`mojo/middle/coro.py` wants `copy.copy(call)` and `copy.deepcopy(node)`, where
`call` and `node` are AST nodes.

`copy.deepcopy` is a **generic walk over an arbitrary object graph**: read
every attribute, decide which are values and which are references to other
objects, allocate a new object per node and repoint the edges. Every step of
that is a capability this target does not have, and they are not one
capability:

* an object with a type tag and readable attributes exists (the gimple runtime
  carries one, and `mojo_obj_getattr` reads it) — so the READ half is
  reachable;
* allocating a new instance of an arbitrary type is not;
* discovering the attribute set of a type at run time is not;
* knowing which attributes are edges and which are scalars is not, and
  guessing gives a copy that shares structure it should not.

So `copy` on this target would be `copy.copy(x) -> x` for a scalar and
nothing else, which is a function whose name promises a graph walk and
delivers an identity. That is the same shape as a wrong `time.time()` and I
filed one of those rather than shipping it.

**What would actually unblock `coro.py`** is a `clone` capability in the
backend — a new node with the same type and freshly-allocated fields — which
is a compiler change, not a module. The doc for it does not exist yet and
should.

## `collections` — 1 file, and the wanted name is a type factory

`formal/lean.py` wants:

```python
Census = collections.namedtuple("Census", "ok detail cached n_sorries …")
```

`namedtuple` **constructs a type**: a new class with N fields, an
`__init__`, `__repr__`, `_asdict`, iteration and indexing. On this path:

* a type is not a value, so it cannot be returned from a module function, let
  alone stored in a module-level name (`bugs/FORMAL_module_state_no_storage.md`
  covers the storage half);
* `Census(...)` at the use site would then be a call to a name the compiler
  has no declaration for, which is the same class of problem as
  `bugs/FORMAL_from_import_alias_dangles_the_call.md` — the call site has no
  signature to read.

The rest of `collections` is containers: `OrderedDict`, `defaultdict`,
`deque`, `Counter`, `ChainMap`. Same answer — each is an object whose
identity and whose contents have to outlive the call that made it.

So this is not a module-shaped piece of work. It needs a *type* to cross a
boundary, and `doc/ABI.md`'s "Aggregates" section already says structs are
passed by pointer with a reflection-table layout; extending that to
*constructing* a type at run time is a real compiler feature.

## `io` — 1 file, and it is the same as `sys.stdout`

`test_formal_sweep_truth.py` wants `io.StringIO()`:

```python
buf = io.StringIO()
with redirect_stderr(buf):
    L._emit_census(lines)
self.assertIn(expect, buf.getvalue(), …)
```

`StringIO` is a mutable buffer with a read cursor, and CPython's
implementation is a C type with a growable buffer. Here:

* a stream OBJECT is a struct with a cursor and a capacity, and cannot cross
  the boundary as a value;
* the buffer has to GROW as text is appended, and growth is the same
  run-time-length sequence that stops `os.listdir` and SHAKE.

`sys.mojo` already says this at the top of its own file and spells
`sys.stdout.write` as two functions (`write_stdout`, `write_stderr`). `io` is
the same statement one level up: **`io` is `sys`'s streams, and `sys` already
says what it can be.**

What is writable and useful: `io.open` as a thin wrapper over the `os`
module's `open`/`lseek`/`close` (which exist and are tested), and the buffer
constants. What is not: anything with a cursor.

---

## The one-line version

| module | wanted by | blocked on | is it a module? |
|---|---|---|---|
| `glob` | 4 files | `os.listdir` (run-time-length list + `struct dirent`) | partly — the pattern half is |
| `copy` | 1 file | a generic object-graph clone | no — a compiler capability |
| `collections` | 1 file | a type crossing a boundary (`namedtuple`) | no — a compiler capability |
| `io` | 1 file | a growable buffer with a cursor | partly — `sys` already says what `io` can be |

**The pattern in the last column is the useful part.** Two of the four are
compiler capabilities wearing a standard-library name, and two are modules with
a real subset. Writing a module for either of the first two would produce a
function whose name promises something the target cannot do — which is the
outcome this project has been most careful to avoid, and which is why all
four are recorded here rather than stubbed.

## The order I would take them in, if the claim is picked up again

1. **`glob`'s pattern half** (`has_magic`, `escape`, `match`). Pure, testable
   against `fnmatch`, and it moves 4 sweep files to their next real refusal.
   Half a day. Do this one.
2. **`io.open`** over the existing `os` calls, plus the buffer constants.
   Small, and it is the honest subset of `io`.
3. **Then stop and look at the two compiler capabilities** — a `clone` for
   `copy` and a constructible type for `collections` — as ONE piece of work
   rather than two module-shaped ones, because they share the root cause
   (nothing with identity or type crosses a boundary) and whoever does it will
   want to know that.
