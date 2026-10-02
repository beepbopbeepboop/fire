# FORMAL: `_frame_receivers` is handed the method-NAME table where it wants the method-OWNER one, so a `None`-constant census crashes

**Area:** FORMAL (`formal/build.py`). **Status: OPEN — a crash with a traceback
out of a compiler, and the fix is one argument at one call site. NOT FIXED HERE
because it is pre-existing on `master` and therefore not anything the merge of
the `formal3-*` branches caused; the area belongs to whoever owns the
class-constant rewrite.** Filed while merging `work/formal3-*` because
`test_dataclasses_formal.py`'s corpus case (`formal/build.py` compiled through
the formal path) hits it on every run, so it is a red line in every gate the
integrator runs.

## What I ran

```
$ python3 -c "import sys; sys.path.insert(0,'.'); import formal.build as B; \
    B.compile_formal('formal/build.py', output='.tmp/corpus.bin', prove=False)"
  File "formal/build.py", line 8703, in refuse_none_comparisons
    fn, structs_by_name, (method_owners or {}).get(fn.name),
  File "formal/build.py", line 6255, in _constant_read_sites
    publish(receiver, owner, comptime_only=True)
  File "formal/build.py", line 6232, in publish
    shadowed = _overridden_comptime_names(structs_by_name, st)
  File "formal/build.py", line 6465, in _overridden_comptime_names
    for derived in M.struct_derived_names(struct_defs.values(), st.name):
AttributeError: 'str' object has no attribute 'name'
```

and, the same defect seen through the suite that reports it:

```
$ python3 test_dataclasses_formal.py
FAIL  the_repositorys_own_dataclasses_are_classified_not_crashed:
      formal/build.py is classified, not crashed: AttributeError:
      'str' object has no attribute 'name'
52 passed, 1 failed          # on master: 50 passed, 1 failed — same failure
```

## What I expect

A file is CLASSIFIED — refused with a sentence naming a construct, or built.
That is the entire assertion of that case, stated in its own docstring: "A file
in this repository that mentions `@dataclass` and crashes the compiler is a
defect in the transform, and a build-only test suite of hand-written cases would
not see it." An `AttributeError` out of a `dict.get` is neither.

## The cause, and it is a name/shape mismatch between two tables that look alike

`_prepare_functions` ends with

```python
_frame_receivers(functions, structs_by_name, dc_equality,
                 imported_bound_names(stmts),
                 star_imported_modules(stmts), owners)
```

and `_frame_receivers`'s sixth parameter is

```python
def _frame_receivers(functions, structs_by_name,
                     dc_classes=None, imported=None, star_imports=(),
                     method_owners=None) -> None:
```

whose own docstring says what it wants: "`method_owners` is `{function name:
struct}`". What it is given is `owners`, which is `_method_owners(stmts,
extra_structs)` — and that one is `{BARE method name: STRUCT NAME}`:

```python
def _method_owners(stmts, extra_structs) -> dict:
    """{method_name: struct_name} for every method a module declares.
```

Two different tables, both called "owners", one keyed by the lifted
`<Struct>_<method>` a rewritten call spells and carrying a `StructDef`, the other
keyed by the bare name a `MemberExpr`'s `.member` is and carrying a `str`. The
value then travels:

```
refuse_none_comparisons  (formal/build.py:8703)
  -> _constant_read_sites(fn, byname, owner=<str>, …)
  -> publish(receiver, owner, comptime_only=True)          (6255)
  -> _overridden_comptime_names(structs_by_name, st)       (6232)
  -> st.name                                              (6465)  AttributeError
```

Note that the crash is only reached when the check gets past its own guard,
`if not none_names and not none_consts: return` — so it needs a struct in the
unit with a class-level `None` binding. `formal/build.py` has one; that is the
only reason the corpus case finds it and a hand-written case does not.

## Why `formal/build.py` and not any file

`owners` is `_method_owners(stmts, extra_structs)`, and `extra_structs` carries
the declarations of everything the unit IMPORTS. So the collision needs a
module-level function whose name is a bare method name of an IMPORTED struct.
Measured, for this file:

```
$ Parser methods: ['__init__', '_parse_funcdef', …, 'parse_module', …]
$ collisions with formal/build.py's module-level defs: ['parse_module']
```

`formal/build.py` defines its own module-level `def parse_module(...)` at line
81, and `fire_compiler.Parser.parse_module` is the method. That is the pair.
This is a shape a corpus produces by accident and a hand-written test never
produces on purpose — which is the argument for the case existing.

## The next step

**One argument at one call site**, and then a check that the two tables can
never be confused again:

1. pass the table the parameter is documented to want. `M.method_owner_names
   (structs)` is the one (`{function name: StructDef}`), and `_frame_receivers`
   already builds it internally as the local `owners` at its line 2650 — so the
   honest fix is to pass that one and, if the local is still needed under the
   other name, RENAME one of the two locals so the next reader is not misled
   again. (Do NOT simply delete the argument: `refuse_none_comparisons` at 3094
   and the `publish` call at 6255 are the only consumers of the parameter, and
   the receiver census is what makes a `None`-valued `comptime` read through a
   receiver a refusal rather than a `0 == 0`.)
2. the guard that makes this a CRASH rather than a wrong answer is already
   there and cheap to keep: `struct_derived_names` already does
   `getattr(st, "name", None)` throughout, so a `None`-tolerant
   `struct_defs.get(...)` in `_overridden_comptime_names` costs nothing — but
   the real fix is (1), and (2) alone would be a refusal-free silence.

**A test for it belongs in `test_dataclasses_formal.py`'s corpus case, which
already fails and would go green** — plus, if the owner wants the construct
rather than the accident, a two-file case: a module that imports a struct and
declares a module-level function with one of its method's names, with a
class-level `None` binding somewhere in the unit. That is the minimal shape, and
it is worth adding because the corpus case is a `formal/build.py` test wearing a
generic name.
