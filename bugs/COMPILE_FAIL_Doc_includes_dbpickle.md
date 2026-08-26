# COMPILE_FAIL: Doc/includes/dbpickle.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py`

## Status (re-verified 2026-08-26, branch fix/opencode-importlib — DOCUMENTED-NOT-FIXED, unchanged)

Re-ran the full `python3 mojo.py build` repro fresh under the memory/
time watcher: fails at 76s with the IDENTICAL single error signature
(`dbpickle.py:80:3: error: cannot convert to a pointer type` at
`DBUnpickler(file, conn).load()`). Also re-checked the tree directly:
still zero references to `BytesIO`/`StringIO`/`Pickler`/`Unpickler`
anywhere in gimple_codegen.py or runtime/. None of the recent shared
mechanism landings touch this file's shape (it has no generators; its
needs are two from-scratch runtime subsystems). Assessment unchanged:
a real growable byte-buffer `io.BytesIO` plus a subclassable pickle
engine honoring `persistent_id`/`persistent_load` overrides — each
comparable in scope to the existing sqlite3 binding, and the pickle
engine additionally needs real user-subclass virtual dispatch.
Doc/includes/ example code, low value relative to effort; not
attempted.

## Status (re-verified 2026-08-25, worktree fix/rest-remainder12 — DOCUMENTED-NOT-FIXED, unchanged)

Re-ran an isolated `compile_to_gimple` check fresh against this
session's other landed fixes (coroutine-body `mojo_c_getenv`/print/
string-repeat/f-string fixes — see COMPILE_FAIL_Apple___main__.md);
none are relevant here (this file has no generator/coroutine bodies at
all — it's a plain-function `io.BytesIO`/`pickle.Pickler` gap). Still
zero references to `BytesIO`/`StringIO`/`Pickler`/`Unpickler` anywhere
in gimple_codegen.py or the runtime. Assessment unchanged from
2026-08-23: two separate missing runtime subsystems (a real
`io.BytesIO` byte-buffer type, and a subclassable `pickle.Pickler`/
`Unpickler` honoring `persistent_id`/`persistent_load` overrides),
each comparable in scope to the existing sqlite3 binding. Not
attempted — genuinely feature-sized, and this is Doc/includes/ example
code, not real library source. Doc kept open.

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — DOCUMENTED-NOT-FIXED, assessment reconfirmed)

Re-ran the repro (same `dbpickle.py:80:3: error: cannot convert to a
pointer type` at the `DBUnpickler(file, conn).load()` call) and
re-confirmed the gap is unchanged: still zero references to
`BytesIO`/`StringIO`/`Pickler`/`Unpickler` anywhere in gimple_codegen.py
or the runtime. The two missing features are assessed as NOT tractable
for a single-session fix, concretely:

1. **io.BytesIO** — needs a real growable byte-buffer runtime type with
   the read/write/seek/getvalue protocol and codegen wiring (a new
   fixed-layout struct + `_KNOWN_SIGS` entries + method dispatch),
   comparable in scope to the existing sqlite3 binding cited below.
2. **pickle.Pickler/Unpickler** — this example's entire purpose is the
   CUSTOM-SUBCLASS protocol (`class DBPickler(pickle.Pickler)` overriding
   `persistent_id`, consumed by `persistent_load`), so stubbing is not an
   option: it needs a real pickler engine whose dispatch honors user
   subclass overrides — a full feature, not a shim.

A minimal BytesIO-only shim would let the file compile but produce
silently-wrong output (the pickle stream would be garbage), which this
project's conventions explicitly forbid. Marking DOCUMENTED-NOT-FIXED;
worth revisiting only if a higher-value stdlib file independently needs
the same subsystem.

## Status (re-verified 2026-08-09, still open)

Root-caused; NOT fixed — requires implementing two substantial missing
runtime features (`io.BytesIO`, `pickle.Pickler`/`Unpickler`), not a
narrow bug. Low priority: this is a Doc/includes/ EXAMPLE script (doc
illustration code), not real library/stdlib code.

Re-verified against current master (`python3 mojo.py build
Doc/includes/dbpickle.py`): `gimple_codegen.py` still has zero
references to `BytesIO`/`Pickler`/`Unpickler` anywhere in the file, so
the underlying gap is unchanged. The GCC error site has shifted slightly
(now surfaces one statement later than previously recorded, at the
`DBUnpickler(...).load()` call rather than the `io.BytesIO()` assignment
itself — an artifact of unrelated codegen changes upstream, not of any
fix to this gap):

```
dbpickle.py:80:3: error: cannot convert to a pointer type
   80 |     memos = DBUnpickler(file, conn).load()
```

which still traces back to the same root cause below: `file = io.BytesIO()`
(line 68) lowers to an unresolved stub returning `int64_t`, and that
`int64_t`-typed `file` conflicts with later pointer-typed uses.

## Root cause

`io.BytesIO` has NO runtime support in this compiler at all (confirmed:
zero references to `BytesIO`/`StringIO` anywhere in gimple_codegen.py).
`io.BytesIO()` lowers as an unresolved dynamic member-call stub
("`int64_t.BytesIO() stubbed`" in the generated C, `dbpickle.ci:1430`),
returning a bare `int64_t`. `file` is later used in contexts requiring a
real pointer (`DBPickler(file).dump(...)`, `file.seek(0)`,
`DBUnpickler(file, conn).load()`), so a later inferred pointer type for
`file` conflicts with the earlier `int64_t` stub value at its assignment
— "cannot convert to a pointer type".

Separately (not yet independently confirmed to compile past this point,
since the build fails before reaching it), `pickle.Pickler`/
`pickle.Unpickler` ALSO have zero runtime support (no references
anywhere in gimple_codegen.py) — this example's whole point is the
`persistent_id`/`persistent_load` custom-pickling protocol
(`class DBPickler(pickle.Pickler): def persistent_id(self, obj): ...`),
which would need real subclassable `Pickler`/`Unpickler` base-class
support, not just a stub.

For comparison: `sqlite3` (also used in this file, `sqlite3.connect`,
`cursor.execute`, `cursor.fetchone()`) already has a REAL runtime binding
(`mojo_sqlite3.h`, wired up via `_KNOWN_SIGS` at
gimple_codegen.py:4957-4966) — `io.BytesIO`/`pickle.Pickler` would need
equivalent from-scratch runtime + codegen work: a growable byte-buffer
struct with `read`/`write`/`seek`/`getvalue`, and a real
`pickle.Pickler`/`Unpickler` implementation supporting subclass
overrides of `persistent_id`/`persistent_load`.

## Priority note

Not attempted — this is a genuinely new-feature-sized gap (two separate
missing runtime subsystems), not a quick fix, and the specific file
affected is Doc/includes/ EXAMPLE/illustration code (not real
library/stdlib source), so its value relative to effort is low compared
to other remaining bugs. Worth revisiting only if `io.BytesIO` or
`pickle.Pickler`/`Unpickler` support becomes independently motivated by
some OTHER, higher-value real stdlib file that needs the same feature.
