# `self.X: list = []` inside `__init__` gives the struct field the type `struct Parser *`

## Status: OPEN. Found 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`;
## pre-existing, and reachable only through the rollback that bug removed.

## What I ran

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

and the generated-C error inventory described in that doc's "How it is measured
now" section, which reports 1 of the 11 remaining errors as

    fire_nl.ci:1058571:9: error: assignment to 'MojoList *' from incompatible
        pointer type 'struct Parser *' [-Wincompatible-pointer-types]

## What I saw

In `fire_compiler_Parser__skip_comptime_rhs`, at `fire_compiler.py:4306`
(`self._comptime_rhs_failures.append((_where, _rhs_text, str(e)))`):

    _t104 = self->_comptime_rhs_failures;      // _t104 : MojoList *

and the struct it is read out of, at `fire_nl.ci:1235`:

    typedef struct Parser {
      int64_t __mojo_type_id;
      MojoList * _tok;
      int64_t _pos;
      char * _filename;
      MojoList * _pending_decs;
      MojoSet * _known_traits;
      struct Parser * _comptime_rhs_failures;   // <- wrong
    } Parser;

The field's declared type is the RECEIVER's struct pointer. It is annotated
`list` at its one definition, fire_compiler.py:3334, inside `__init__`:

    self._comptime_rhs_failures: list = []

so the annotation is right there and is being ignored; `struct Parser *` is the
shape a bare `self.X = <expr>` field gets when nothing narrows it.

## Why

`struct_field_types` for a sibling-compiler class is built by
`mojo/middle/module_shared.py`'s struct passes and by
`module_gen.py`'s `_is_selfhost_source_file` block (which hand-declares
`Scope`, `Token`, `ReturnValue`, `MojoFunction`, `_MojoSortFn`,
`_ComplexFloat` and others and NOT `Parser`). Whatever pass derives `Parser`'s
fields is reading the `self.X = ...` assignments and, for this one, concluding
the receiver's type — most likely a "field initialised from a constructor-call
or unknown expression" fallback that mirrors the enclosing struct. Every OTHER
`Parser` field came out right (`_tok`/`_pending_decs` as `MojoList *`,
`_known_traits` as `MojoSet *`), so the shape is read correctly elsewhere and it
is the ANNOTATION on this one assignment that is not being consulted.

## Exact next step

Find the pass that fills `struct_field_types['Parser']` for a self-host source
file and make it read a `self.<name>: <annotation> = <rhs>` assignment's
annotation the way it already reads a class-body annotated attribute
(`_class_attr_ctype` in mojo/middle/types.py:672 is the existing
annotation-to-C-type answer, and
`_selfhost_struct_dict_field_val_types` in module_shared.py:229 is the
neighbouring pass that gets the same information for `dict` value types).

The test that would have caught it: for every self-host class, assert that each
`self.<name>: T = ...` assignment's `<name>` field's declared C type is the one
`_class_attr_ctype(T)` gives, rather than whatever the RHS inference produced.