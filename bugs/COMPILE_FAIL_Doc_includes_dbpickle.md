# COMPILE_FAIL: Doc/includes/dbpickle.py

Source file: `/Users/mrs/net/Python-3.14.6/Doc/includes/dbpickle.py`

## Status (updated 2026-08-06)

Root-caused; NOT fixed — requires implementing two substantial missing
runtime features (`io.BytesIO`, `pickle.Pickler`/`Unpickler`), not a
narrow bug. Low priority: this is a Doc/includes/ EXAMPLE script (doc
illustration code), not real library/stdlib code.

```
error: cannot convert to a pointer type
```
at:
```python
file = io.BytesIO()
```

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
