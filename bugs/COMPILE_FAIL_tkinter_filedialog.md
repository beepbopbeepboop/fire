# COMPILE_FAIL: Lib/tkinter/filedialog.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/tkinter/filedialog.py`

## Status (updated 2026-08-06)

The ORIGINAL symptom (`_Open_show` undefined at link time — a dotted base
class `_Dialog(commondialog.Dialog)` losing its base-class name during
parsing, compounded by `from tkinter import commondialog` never being
recognized as "also compile the submodule file") is FIXED — see commit
`a907260` (mojo_compiler.py's dotted-base-class parsing +
gimple_codegen.py's `from package import submodule` resolution).

A NEW, deeper issue is now exposed instead:

```
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:42:6: error: conflicting types for 'tkinter_commondialog_Dialog___init__'; ...
/Users/mrs/net/Python-3.14.6/Lib/tkinter/dialog.py:13:7: error: 'Dialog' has no member named 'widgetName'
```

`tkinter/dialog.py` and `tkinter/commondialog.py` each define their OWN,
DIFFERENT class literally named `Dialog`. Real Python has no ambiguity —
`filedialog.py` does `from tkinter.dialog import Dialog` (binds the bare
name `Dialog` to the FIRST one) and separately `from tkinter import
commondialog` + `commondialog.Dialog` (the qualified reference to the
SECOND one) — but this codegen's struct registration is keyed by BARE
NAME only ( `struct_field_types['Dialog']`, `_struct_name_owner`'s
"first StructDef seen under a given name wins entirely" — see its own
docstring in gimple_codegen.py), so the two distinct real classes collide
into one struct definition, and whichever one lost gets alien method
bodies from the other (e.g. `tkinter/dialog.py`'s own `Dialog.__init__`
body, which references `self.widgetName`/`self.num` — fields that only
exist on tkinter/dialog.py's Dialog, not commondialog.py's — compiled
against commondialog.py's Dialog struct layout instead).

## What a real fix needs

This codegen's struct-naming model assumes one bare class name maps to
exactly one real class within a whole transitive-closure compile — true
almost everywhere, but not here. A real fix needs cross-module-qualified
struct identity for genuinely same-named-but-different classes: either
(a) always qualify struct names by their home module internally (bare
name only at the surface, for user-facing symbols that don't collide),
falling back to a qualified name only when TWO real StructDefs actually
do share a bare name across modules (mirroring `_struct_name_owner`'s
existing by-identity collision GUARD — currently it only detects and
picks a winner, doesn't actually keep both), or (b) at minimum, error
out loudly on this specific case (two real, both-referenced-in-this-
compile classes sharing a bare name) instead of silently merging them
into one corrupted struct. Not attempted here — a real architectural
change to struct-identity tracking, not a targeted patch.
