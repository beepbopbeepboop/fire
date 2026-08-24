# COMPILE_FAIL: Lib/importlib/metadata/_collections.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/metadata/_collections.py`

## Status (updated 2026-08-23 — RESOLVED, builds clean)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
importlib/metadata/_collections.py` fresh against master `626f3f0`:
**exit code 0, a linked executable is produced**
(`Built: .../_collections`). The 2026-08-06/08-09 blocker below
(`Pair.parse`'s `return cls(*map(str.strip, text.split("=", 1)))`
producing `non-trivial conversion in 'mem_ref'` off an unmodeled
`collections.namedtuple(...)` base) no longer reproduces — resolved by
upstream work landed between 2026-08-09 and now (the compiled-generator
project's coroutine lowering plus the type-inference/dup-def fixes;
not independently bisected, since the repro is simply green). The two
exotic class-definition shapes the old write-up flagged
(`FreezableDefaultDict(collections.defaultdict)` and
`Pair(collections.namedtuple('Pair', 'name value'))`) both compile on
current master.

Closing this doc as RESOLVED against current master.

## Status (re-verified 2026-08-09 — historical)

Re-ran `python3 mojo.py build .../_collections.py` fresh against current
master. Still fails, byte-identical to the 2026-08-06 finding below:
`_collections.py:31:1: error: non-trivial conversion in 'mem_ref'`
(`_t14 = *_t10;`), i.e. `Pair.parse`'s `return cls(*map(str.strip,
text.split("=", 1)))`. Root cause below still holds — genuinely
structural (would need real modeling of `collections.namedtuple(...)`'s
dynamically-constructed return value as a subclassable struct type,
which is out of scope as a narrow fix). Not attempted.

## Status (updated 2026-08-06)

Not fixed. Root cause identified but not resolved — a genuinely exotic,
low-value pattern (whole file is 30 lines, two tiny classes).

```
error: non-trivial conversion in 'mem_ref'
```
at:
```python
class FreezableDefaultDict(collections.defaultdict):
    ...

class Pair(collections.namedtuple('Pair', 'name value')):
    @classmethod
    def parse(cls, text):
        return cls(*map(str.strip, text.split("=", 1)))
```

Two unusual class-definition shapes in one tiny file:
1. `FreezableDefaultDict(collections.defaultdict)` — subclassing a
   BUILTIN container type directly.
2. `Pair(collections.namedtuple('Pair', 'name value'))` — subclassing
   the DYNAMICALLY-CONSTRUCTED RETURN VALUE of a factory function call,
   not a real, statically-known class at all.

The error surfaces inside `Pair.parse`'s `cls(*map(str.strip, ...))` —
`cls` (opaque classmethod class-reference) constructing an instance of
a base class this compiler never modeled as a real struct (since
`collections.namedtuple(...)`'s return value isn't a class the compiler
can see the shape of ahead of time) — generated C ends up dereferencing
a `void`/`int64_t`-mismatched pointer (`_t14 = *_t10;`).

Not investigated further or fixed — both patterns are rare/exotic
relative to the file's small size and narrow value, and fixing either
properly would need real support for subclassing dynamically-constructed
types (a namedtuple factory's return value), which is a different and
likely much harder problem than the struct-inheritance gaps already
tracked (bugs/hard/CODEGEN_multiple_inheritance_duplicate_method_
symbols.md covers ordinary multiple inheritance among statically-known
classes, not this).
