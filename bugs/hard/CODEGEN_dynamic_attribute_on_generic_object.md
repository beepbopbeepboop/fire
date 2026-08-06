# HARD BUG: setting/getting an arbitrary attribute on a generically-typed object

## Status

Unfixed. This is a missing capability (real `__dict__`-style dynamic
attribute storage for non-struct objects), not a targeted bug — implementing
it is a new feature, not a patch to one call site.

## Symptom

`request for member 'X' in something not a structure or union` (GCC
`-fgimple` error).

This codegen models attribute access (`obj.field`) as a real C struct-field
read/write, which requires knowing `obj`'s concrete struct layout ahead of
time. When `obj`'s static type can't be resolved to a known struct — most
commonly a bare, unannotated parameter whose real runtime type is something
generic like a class object (`type`) or a closure/function value — it falls
back to a generic `int64_t`/opaque representation with **no** attribute
storage at all. Setting or reading an attribute on it by name (Python's real
`__dict__` semantics — you can attach a brand-new, previously-unseen
attribute to *any* object at runtime) has nothing to lower to.

## Minimal repro

```python
# dynamic_attr_repro.mojo
class Slot:
    def __set_name__(self, cls, name):
        try:
            slotnames = cls.__slot_names__
        except AttributeError:
            slotnames = cls.__slot_names__ = []
        slotnames.append(name)
```

`cls` is the descriptor protocol's second `__set_name__` argument — its real
type is `type` (whatever class this `Slot` was placed on), erased by this
codegen to a generic/opaque value with no field table. Compiling this
(`gcc -fgimple -fsyntax-only` on the generated C, or `python3 mojo.py build
dynamic_attr_repro.mojo`) fails with:

```
dynamic_attr_repro.mojo:6:6: error: request for member '__slot_names__' in something not a structure or union
```

A second, related instance in the same real file: `__del__._slotted = True`
sets an attribute on a locally-defined closure (`__del__`) — same root
cause (attribute set on a generic, non-struct value), surfaces as:

```
clsutil.py:83:7: error: 'MojoBoundMethod' has no member named '_slotted'
```

## Real-world file exposing this

`Tools/c-analyzer/c_common/clsutil.py`'s `Slot.__set_name__` /
`Slot._ensure___del__` (both reproduce today, confirmed via direct
`python3 mojo.py build`):

```
Tools/c-analyzer/c_common/clsutil.py:39:6: error: request for member '__slot_names__' in something not a structure or union
Tools/c-analyzer/c_common/clsutil.py:83:7: error: 'MojoBoundMethod' has no member named '_slotted'
```

(Originally reported via a similar-looking symptom in
`Tools/c-analyzer/c_common/fsutil.py`'s `exc.filename` access — that
specific instance no longer reproduces; see
`CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`'s note on
`fsutil.py` for why. `clsutil.py`'s instance above is confirmed live and
independent of that other issue.)

### Three more real-world instances (confirmed 2026-08-06), same root cause

All three are the SAME underlying gap in a different guise: setting an
attribute on a CLASS-OBJECT reference at module/class-body scope (not
inside `__init__`, where ordinary `self.field = ...` scanning already
registers a real struct field) — `cls.x = ...` inside a classmethod, or
`SomeClass.x = ...` directly at module top level, referring to a class
this codegen elsewhere treats as a real, known struct:

- `Lib/collections/__init__.py`'s `OrderedDict.__new__`: `self =
  dict.__new__(cls)` (an unmodeled `dict.__new__(cls)` call, so `self`'s
  static type is opaque) followed by `self.__hardroot = _Link()` /
  `self.__root = ...` — "request for member '__root' in something not a
  structure or union".
- `Lib/ctypes/__init__.py`: `c_ubyte.__ctype_le__ = c_ubyte.__ctype_be__ =
  c_ubyte` at module top level, setting a NEW attribute directly on a
  locally-defined class object (`c_ubyte`) outside any method — "request
  for member '__ctype_le__'/'__ctype_be__' in something not a structure
  or union".
- `Lib/string/__init__.py`'s `Template.__init_subclass__`: `pat =
  cls.pattern = re.compile(...)` — a classmethod's `cls` parameter, exact
  same shape as the minimal repro above (`cls.__slot_names__ = ...`) —
  "request for member 'pattern' in something not a structure or union".
  (Also breaks `Lib/importlib/__init__.py`, which imports `string`
  transitively.)

## What a real fix needs

A genuine per-object dynamic attribute store (e.g. a runtime hash map keyed
by attribute name, attached to any object whose static type isn't a known
struct) plus codegen support for reading/writing through it whenever static
field resolution fails. This is a new object-model capability, not a
one-off fix.
