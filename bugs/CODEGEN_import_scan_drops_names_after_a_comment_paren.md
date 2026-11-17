# CODEGEN: `_scan_from_imports_flat` truncates a parenthesised import list at a `)` inside a comment

## What I ran

    python3 - <<'EOF'
    from mojo.middle.funcs_shared import _scan_from_imports_flat
    src = '''from .memory import (
        a,
        # TODO(X-1): remove once done
        b,
    )
    '''
    print(_scan_from_imports_flat(src))

    import sys
    sys.path.insert(0, '.')
    from gimple_codegen import GimpleGen
    g = GimpleGen(emit_entry_points=False, module_name='probe')
    print(g._find_generic_source('std.memory', 'forget_deinit'))
    print(g._find_generic_source('std.memory', 'unsafe_destroy_n'))
    EOF

## What I saw

    ['.memory', ' a, # TODO(X-1']
    None
    None

The flattened name list stops at the `)` of `TODO(X-1` inside the comment, so
`b` — and every name after the comment in a real multi-line import — is
invisible to every caller of the scan. On the real stdlib this is not
hypothetical: `std/memory/__init__.mojo`'s `from .memory import (...)` list
contains

    # TODO(MSTDL-2918): Remove this export once the `memmove` deprecation is

before `unsafe_destroy_n` and `forget_deinit`, and both resolve to `None`.

Measured 2026-11-16. With the paren-cut made comment-aware in a throwaway
local copy (strip `#...` before the scan), the same two calls return
`.../std/memory/memory.mojo`.

## Why it matters

`_scan_from_imports_flat` (`mojo/middle/funcs_shared.py`) is the re-export hop
reader behind `funcs_shared._find_generic_source`, `elab_intu._factory_home`'s
import map, and `elab_intu`'s own import scan. A `from .pkg import ( ... )`
list that contains a `#` comment with a parenthesised word (a TODO/JIRA id is
the common shape) silently loses all following names, so the caller-side
elaborator is never even offered those re-exported generics.

This does not block the cross-module generic-instance fix for
`bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs` part 9, which resolves
the measured references from the DEFINING side. Fixing the scan would
additionally let the caller-side elaborator see the re-exported templates,
which is the better path when the type arguments are provable.

## Expected

`_scan_from_imports_flat` should join the parenthesised list to its MATCHING
closing paren, counted by bracket depth, with `#` comments (and string
literals — a `")"` in a docstring has the same shape) excluded from the
count. That is the same hazard `gimple_ctypes._bracket_depth_by_line`
documents and solves for source text; reuse that reader rather than adding a
third bracket scanner.

## Exact next step

1. In `_scan_from_imports_flat`, replace `_cut = _names.find(')')` with a
   depth-counted scan over `lines[_i]` that skips `#` to end of line and
   quoted strings, appending until depth 0.
2. Add a `test_import_scan...` case (next to the existing
   `_scan_from_imports_flat` consumers' tests, e.g. in
   `test_import_integration.py`) for a list whose comment contains `)`.
3. Re-measure `gen._find_generic_source('std.memory', 'forget_deinit')` on
   the real stdlib (must be the defining module's path) and run the
   stdlib-dylib gate to confirm the `skip <module>:` count does not move.
