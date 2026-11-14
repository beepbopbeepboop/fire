# `module_gen.py` compiles in isolation: one dispatch-global import is not ambiguous (part 2)

Part 2 of 3 of `bugs/hard/CODEGEN_dict_slot_reads_refuse_compiler_sources.md`.
Class: easy — one import list names two constants that another import in the
same file already bound; drop the duplicate and say why.

## Measured (2026-11-14, this tree)

`test_dict_slot_read_selfhost_modules.py` (the regression pin for this doc's
compiler-source half) is red on its fourth module:

    $ python3 test_dict_slot_read_selfhost_modules.py
      PASS ast_rewriter.py: compiled (667693 bytes of C)
      PASS mojo/middle/module_shared.py: compiled (2235506 bytes of C)
      PASS mojo/middle/coro.py: compiled (6962680 bytes of C)
      FAIL mojo/backend_gimple/module_gen.py: refused
    FAILED:
      mojo/backend_gimple/module_gen.py: refused:
      module_gen.py:120:1: error: import of '_LIST_RETURNING_METHODS' is ambiguous
      ... error: import of '_STR_RETURNING_METHODS' is ambiguous

The three modules this doc originally refused (`ast_rewriter.py`,
`module_shared.py`, `coro.py`) are green; `module_gen.py` — a module of the
compiler's own source that the self-host closure builds — does not compile
through the same `compile_module_to_c(..., linkable=False)` entry.

## Why

`_LIST_RETURNING_METHODS` and `_STR_RETURNING_METHODS` each have two real
definitions: `gimple_codegen.py:131-132` defines its own sets, and
`mojo/middle/types.py:1454-1455` defines a second pair which
`mojo/middle/module_shared.py:2121` re-exports. `mojo/backend_gimple/module_gen.py`
imports both names twice in module scope:

- line 107: `from gimple_codegen import ..., _LIST_RETURNING_METHODS, ..., _STR_RETURNING_METHODS, ...`
- line 121: `from mojo.middle.module_shared import _LIST_RETURNING_METHODS, _STR_RETURNING_METHODS, ...`

The module-scope ambiguity diagnostic added in `201d8ad37`
(`DIAGNOSTICS_formatting_modular` part 2) is right to fire on two DISTINCT
definitions of one name. Measured on a scratch copy of the module: removing
those two names from the line-121 list makes the module compile — 15,113,430
bytes of C — so this is the whole blocker, not the first of several.

## Goal

`mojo/backend_gimple/module_gen.py` compiles through
`build_stdlib_dylib.compile_module_to_c(..., linkable=False)` like the other
compiler modules, and each dispatch constant has exactly one import site in the
file.

## Acceptance

- `mojo/backend_gimple/module_gen.py` compiles and yields C (no refusal), via
  the same entry point and arguments the test uses.
- `_LIST_RETURNING_METHODS` and `_STR_RETURNING_METHODS` are bound from ONE
  module in `module_gen.py` — the `gimple_codegen` sets are the ones its
  codegen path uses, so keep those and drop the duplicate from the
  `module_shared` list. Do not add a third definition or a compatibility alias.
- `test_dict_slot_read_selfhost_modules.py` reports ALL PASS.
- `test_pin_dispatch_globals_list_fixed.py` still passes (it pins the same
  names as `MojoSet *` in `mojo.middle.types`' dispatch-global table; this part
  changes an import list, not that table).
- `test_dict_slot_read_regression.py` stays green.

## Done when

File: `test_dict_slot_read_selfhost_modules.py` (repo root).

Command: `python3 test_dict_slot_read_selfhost_modules.py`

It is red today on `module_gen.py` (output above) and must print `ALL PASS`.

## Where to start

- `mojo/backend_gimple/module_gen.py:107` — the `gimple_codegen` import that
  already binds the two names; keep it.
- `mojo/backend_gimple/module_gen.py:121` — the `mojo.middle.module_shared`
  list; drop `_LIST_RETURNING_METHODS, _STR_RETURNING_METHODS` and add a
  one-line comment naming the duplicate definition.
- `mojo/middle/import_ambiguity.py` — the diagnostic; no change is expected
  here. This part removes the genuine duplicate, it does not weaken the check.
