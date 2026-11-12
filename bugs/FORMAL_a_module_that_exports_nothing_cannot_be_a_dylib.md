# FORMAL: a module that exports nothing cannot be built as a dylib, and its importers should read its constants

Status: OPEN. Filed 2026-11-11 on master. The refusal is correct and stays; the rule that would remove it is not built.

## What is refused, and why

A module with no function and no type, only module-level constants, is refused as a dylib with the exports-nothing
wording (`formal/build.py`, the "exports nothing under doc/ABI.md's rules" message). Today that is `import collections`:
`formal/hostmods/collections.mojo` declares only constants, so the build cannot produce a library from it, and the
refusal is right: a constant is not a boundary symbol, so there is nothing an importer could bind.

## What would remove the refusal

Two things, and neither is in the tree:

1. **A module nothing binds a concrete name from needs no library at all.** An importer that reads a module-level constant
   could take its value directly from the source, without linking a library for the module. That is a backend rule. It
   is not implemented, so an importer of a constants-only module is refused.
2. **A value model for a container-valued module constant.** `collections` has constants whose values are containers,
   and inlining them at the use site needs storage this path does not have.

Until both exist, the refusal stays. The advice for `collections` (write a struct for the record the caller wants) is the
answer the reader can act on today.

## Decided behaviour

- A host module whose source exports nothing is refused with the HOST-MODULE wording and its advice (`unresolvable_import_error`),
  not with the exports-nothing wording. The reader wrote `import collections`; the advice answers that import.
- The exports-nothing wording stays for a non-host module, where no advice applies.

## Related

- `bugs/TEST_formal_imports_host_module_tables_drifted_from_hostmods.md`: the test rows that pin this behaviour.
