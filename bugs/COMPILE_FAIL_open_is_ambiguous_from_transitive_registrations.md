# COMPILE_FAIL: `'open' is ambiguous` refuses any program whose closure contains two modules that define `open`

`fire.py build` on several real CPython files now ends in an honest
module-level refusal that has nothing to do with the file:

```
Error building: cannot compile module: 'open' is ambiguous — this program
transitively imports two different sibling modules that both define a free
function named 'open', each from a different lexical scope (e.g. two
different nested `from X import ...` statements), and no enclosing
`from X import ...` statement in the current lexical scope binds the name
for this specific reference.
```

## What I ran

```
python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py
```

`Lib/zipfile/__init__.py`'s OWN compile unit is CLEAN — zero
`error:` lines at a `zipfile/__init__.py` line — and the build still
refuses the whole program on this message. So for this file the
ambiguity refusal is now the ONLY thing standing between it and a
built binary, which makes it worth getting right rather than working
around.

`Lib/zipfile/__init__.py` never imports `open`:

```python
import binascii, importlib.util, io, os, shutil, stat, struct, sys, threading, time
...
    with open(filename, "rb") as fp:            # line 266, module level
...
    def open(self, name, mode="r", pwd=None, *, force_zip64=False):   # ZipFile.open, a METHOD
```

The bare `open(...)` references are the **builtin**. Python's own
resolution order is local → enclosing → global → builtin, and nothing
here binds the name, so there is nothing to be ambiguous about.

## Root cause

`_func_qualifier` (`mojo/backend_gimple/emit_funcs.py`) has three tiers:
local top-level def → per-lexical-scope import map (`_import_scope_stack`)
→ the flat `_own_imported_func_home` dict. The refusal is raised from
tier 2's `_AMBIGUOUS_FUNC_HOME` marker, after the scope-chain walk
found nothing.

Instrumenting `_note_own_func_home` for `bare_name == 'open'` during
that build shows the flat dict being poisoned by SIX unrelated sibling
modules, all with `record_scope=False`, from the transitive discovery
pass (`gen_module_impl`'s `self._note_own_func_home(_ms.name, _mn,
record_scope=False)`, module_gen.py:1962):

```
REGISTER open home='codecs'                            scope=False module='._win_cp_codecs'
REGISTER open home='tokenize'                          scope=False module='linecache'
REGISTER open home='bz2'                               scope=False module=''
REGISTER open home='compression.zstd._zstdfile'        scope=False module='compression.zstd'
REGISTER open home='lzma'                              scope=False module=''
```

Two of them landing on the same key is all it takes to flip it to
`_AMBIGUOUS_FUNC_HOME` — and `_func_qualifier` then refuses EVERY
reference to `open` in the whole program, including the ones in modules
that imported nothing of the kind.

Two things make this sharper than the docstring's stated model:

1. **`_own_imported_func_home` is documented as per-instance.** Its own
   comment says it is "THIS exact gen_module call's own FromImportStmt
   scan … operating only on `stmts`, never shared across temp_gens", and
   `_compile_imported_module` shares `_imported_func_home` (tier 3) by
   object identity but is documented as leaving tier 2 alone. The trace
   above shows registrations made while compiling `linecache`,
   `codecs`, `bz2`, `lzma`, `compression.zstd` landing on the same
   instance, so either the sharing is wider than documented or
   `_register_link_imports` re-registers into the ROOT instance. Either
   way a reference inside `zipfile` is decided by what `bz2` and `lzma`
   imported.
2. **A `record_scope=False` registration carries no per-reference
   information at all.** It is a whole-program observation ("some module
   in this closure has a function called `open`"). Colliding two of those
   does not mean the reference at hand is ambiguous — it means the
   whole-program observation is useless. Refusing on it converts a
   low-information fact into a hard error on an unrelated module.

## Expected

`Lib/zipfile/__init__.py` builds, because `open` is a builtin there.

## Next step

The Python-faithful rule is already stated by the tiers themselves: a
bare name is resolved by the innermost enclosing scope that binds it, and
only then by module scope, and a name that NO scope binds is a builtin.
So the tier-2 flat dict must not be able to produce a refusal for a name
the module being compiled never lexically imported. Concretely, in
`_func_qualifier`:

- Consult `_own_imported_func_home` for a name only if this module's own
  lexical scope stack binds it (i.e. the scope-chain walk above already
  found it — which is the case it exists to resolve), OR the instance
  genuinely recorded a `record_scope=True` import for it. Today the walk
  runs first and RETURNS, so the only way to reach the flat dict with
  nothing in scope is the `record_scope=True`-with-empty-scope-stack case,
  which is worth auditing separately.
- With that, an `_AMBIGUOUS_FUNC_HOME` entry that no lexical scope backs
  should fall through to tier 3 and then to `''` (builtin), not raise.

**Check first whether the scope stack is populated for the common
module-level `from X import f` case** — `_note_own_func_home` only
writes the scope entry `if record_scope and scopes:`, so a
module-level import processed before any scope is pushed lands in the
flat dict only. If that case is real, the fix has to push a module scope
before the import scan rather than weaken the tier.

Regression test: the shape is a three-file program where the entry
module uses the BUILTIN `open` and two transitively-imported siblings
each define their own `open`. On the broken tree the entry is refused
with the message above; afterwards it builds and its `open` reads a real
file. `test_link_mode.py` already has weak-stub/ambiguity neighbours to
sit beside (`tri: unavailable in compiled mode`), so put it there or in
`test_import_integration.py` rather than opening a new file.

## Why this was not fixed in the same commit

It is a change to `_func_qualifier`'s tier order — the machinery
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
owns, and which several recent entries in this repo call out as broad-
blast-radius and easy to regress into a silent wrong call (picking
either home without an error). The two fixes that DID land alongside it
(`b501954c`, `6a7c69fd`) were each one defect with a bounded blast
radius and a test that fails before them; this one needs the scope-stack
audit above first, and a wrong guess here silently calls the wrong
module's `open` on a whole class of programs.
