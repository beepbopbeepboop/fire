# FORMAL_sweep_relative_import_bind_name_shape_moved: the `lstrip("_")` guard no longer has an end-to-end fixture

## Status

**Partial.** The red assertion is fixed and the invariant it was standing for is
now asserted in a form that does not depend on a name shape that has moved. What
is still missing is an end-to-end fixture that can make the *original* defect
reproduce, and nobody should read "the guard moved" as "the defect is covered
end to end".

Found while fixing `sweep5:sweep-timeouts-x86` (the x86-64 slice of the
`formal_sweep`'s `tool` class). Not that task's subject; recorded here rather
than fixed there.

## What was red, and why

`test_formal_sweep.py`'s
`TestDyldProbe.test_a_relative_imports_underscored_symbol_resolves_and_the_image_runs`
failed on `master` at `24068a01`, before any of this branch's edits:

```
AssertionError: False is not true : precondition: every bind name is
underscore-prefixed, got ['relpkg__helper_twice_9f63a2']
```

The test's fixture builds a package `relpkg/` with `_helper.mojo` and imports it
relatively (`from ._helper import twice`). Its assertion was that the resulting
bind names start with `_`, because a relative import's ABI prefix used to begin
with one — `abi_module_name('._helper')` was `__helper`, and every symbol the
module exported began with `__`. That was the whole reason the probe had to stop
stripping a "leading underscore": `lstrip("_")` turned
`__helper_twice_…` into `helper_twice_…` and reported a load failure for an
image that loads.

Relative imports now **carry their parent's identity**, so the same fixture's
module identity is `relpkg._helper` and the prefix is `relpkg__helper`. That
change landed in `formal/build.py` as `own_module_identity(source_path,
source_path)`, and its own comment states why: without it a relative import at
the root resolved differently depending on which module reached the file first,
so the same source produced `___syscalls.<digest>.arm64.dylib` built on its own
and `__syscalls.<digest>.arm64.dylib` reached as `.path`, with the exports
mangled to match. Two libraries and two export spellings for one file. This
test's prose and precondition were not updated with it.

```
binds:   ['relpkg__helper_twice_9f63a2']
dylib:   ~/.gmojo/cas/formal-imports/arm64/relpkg__helper.810655b26e66.arm64.dylib
exports: ['_relpkg__helper_twice_9f63a2']
lstrip("_") changes the bind name?  False
_unresolved_imports(image)          []
run: exit 42, no stderr
```

So the compiler is fine — the image builds, the probe resolves it, and dyld runs
it to the right answer — and the **test's description of the name shape** is what
went stale. `test_formal_cross_module.py` describes the same property in its
module docstring ("`abi_module_name('._helper')` is `__helper`") and is also out
of date, but its three relative-import cases still PASS (25/25 measured), because
they assert behaviour rather than a spelling.

## What was done

The precondition now asserts the invariant the test actually needs, which is
shape-independent:

> a bind name is the C name and an export is that name with dyld's one
> underscore in front, so the two must be DIFFERENT strings

## What is NOT done, and the exact next step

`lstrip("_")` is now a **no-op** on every name this fixture produces, so the
end-to-end path through `test_formal_sweep.py` can no longer make the original
defect reproduce. The defect is pinned at the probe level instead, by two cases
added alongside the export-trie work:

* `test_the_two_arms_of_the_lookup_agree_on_a_library_both_can_read` — for a
  library this host can `dlopen`, the export trie and `dlsym` must agree on
  **every** name in the table. Measured over the CAS's own arm64 dylibs: 343
  formal-module exports, 343 agreements. The first version of the static arm
  disagreed on all of them and reported all three binds of
  `formal/hostmods/ast.mojo` unexported.
* `S._macho_symbol`'s spelling, asserted directly: exactly one underscore
  prepended, never stripped.

To restore an end-to-end fixture, find a module whose ABI prefix genuinely
begins with `_` — i.e. one reached by a relative import whose parent contributes
nothing to its identity. Candidates, in order of cheapness:

1. A relative import inside a module that is itself a top-level `.mojo` file
   with no package (`from . import helper` in `pkg.mojo` at the repo root). Check
   `formal/imports.py`'s `_module_identity(module, parent)` for what it produces
   when `parent` is None — if it returns `._helper` rather than a qualified
   spelling, that fixture exists and is a two-line addition to `setUpClass`.
2. A module whose own NAME begins with `_` and is imported absolutely
   (`from _helper import f`), which `formal/hostmods/re.mojo`'s `__init__.py`
   already does for the `os` hostmods.

Whichever is chosen, the new case should build the image for **both**
architectures and assert `_unresolved_imports == []` on each, since the
x86-64-foreign case is the one that now goes through the export trie.

## How it was measured

```
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 test_formal_sweep.py          # 79 tests, 1 failure — the one above
$ python3 test_formal_cross_module.py   # PASS=25 EXPECTED=0 FAIL=0
```

Both under `python3 tools/memslot.py --gb 8 --label t --`. The per-name dump
above is a throwaway script that builds `relpkg/__init__.mojo` with
`fire.py build --formal --no-prove --backend=arm64` into a temp dir and then
reads the image back with `tools/formal_sweep.py`'s `_binds`,
`_load_dylib_names`, `_unresolved_imports` and `formal.build.macho_dylib_exports`.