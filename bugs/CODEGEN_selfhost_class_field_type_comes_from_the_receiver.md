# A self-host class's field type comes from the receiver, not from the field's own assignment — `Parser._comptime_rhs_failures`, `MojoFunction._interp`

## Status: OPEN. Four of the eleven errors `selfhost` now reports. Found
## 2026-10-03 while working
## `bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`;
## pre-existing, and reachable only through the rollback that bug removed.

One defect, four errors, and it is the same answer in all four: the struct field
is typed with a POINTER TO THE RECEIVER'S OWN STRUCT.

## What I ran

    python3 tools/suite.py mojoc bootstrap-stage2-cc
    # FAIL  mojoc  (274s)  exit 2
    # FAIL  bootstrap-stage2-cc  (4s)  exit 2

`bootstrap-stage2-cc` is the useful of the two: it compiles the same self-host
closure and gcc prints the whole failing construct, while `mojoc`'s output the
runner keeps only a tail of. Its tail:

    myinterpreter.py: In function 'myinterpreter__MojoBoundComptimeFunction___call__':
    myinterpreter.py:1076:1: error: non-trivial conversion in 'component_ref'
    1076 |
          ^
    int64_t
    struct MojoFunction *
    _t2 = func->_interp;

    myinterpreter.py: In function 'myinterpreter_MojoOverloadSet___init__':
    myinterpreter.py:1102:1: error: non-trivial conversion in 'var_decl'
    struct MojoOverloadSet *
    int64_t
    self->_interp = _t6;

    myinterpreter.py: In function 'myinterpreter_MojoOverloadSet___call__':
    myinterpreter.py:1168:1: error: non-trivial conversion in 'component_ref'
    int64_t
    struct MojoOverloadSet *
    _t1 = self->_interp;

gcc reads those three lines as: the destination is `int64_t` and the source is a
`struct MojoFunction *` / `struct MojoOverloadSet *` — that is, `_interp`'s
DECLARED FIELD TYPE is the receiver's own struct pointer.

The fourth, from `selfhost`'s own inventory (the stripped-`.ci` method in
`bugs/hard/CODEGEN_dispatch_globals_list_forces_every_name_to_a_dict.md`):

    fire_nl.ci:1058571:9: error: assignment to 'MojoList *' from incompatible
        pointer type 'struct Parser *' [-Wincompatible-pointer-types]
    # 1058571:  _t104 = self->_comptime_rhs_failures;     (_t104 : MojoList *)

## What I saw

Three of the four are the SAME field name in three classes, and the declared
layout table is what makes it legible. `mojo/backend_gimple/module_gen.py:2548`
declares this compiler's own runtime classes by hand, and none of those three
entries has the field:

    self.struct_field_types['MojoFunction'] = {
        'name', 'params', 'body', 'closure_scope', 'comptime_params', '_pd',
        'is_generator', 'is_async',
    }                                    # no '_interp'
    self.struct_field_types['_MojoBoundComptimeFunction'] = {
        'func': 'MojoFunction *', 'comptime_bindings': 'MojoDict *',
    }                                    # no '_interp'
    self.struct_field_types['MojoOverloadSet'] = {
        'name': 'char *', 'candidates': 'MojoList *',
    }                                    # no '_interp'

and the emitted C struct has it anyway, typed as the receiver:

    typedef struct MojoFunction {
      ...
      struct MojoFunction * _interp;
    } MojoFunction;

The source is ordinary and says nothing that would produce that:

    myinterpreter.py:189    self._interp = interpreter
    myinterpreter.py:1074   interp, args = _split_invoker(func._interp, args)
    myinterpreter.py:1101   self._interp = interpreter
    fire_compiler.py:3334   self._comptime_rhs_failures: list = []

`interpreter` is an UNANNOTATED `__init__` parameter, so the honest answer is
the box; `_comptime_rhs_failures` is ANNOTATED `list`, so its honest answer is
`MojoList *`. Both got the receiver's struct pointer instead. So the annotation
is not merely ignored on the unannotated one — it is ignored on the annotated
one too.

## Why this is a table-completeness problem as much as an inference one

Two independent facts, and both matter:

* **The hardcoded layouts are incomplete, and the gap is filled with the wrong
  thing rather than with nothing.** `_MojoSortFn` DOES carry
  `'_interp': 'int64_t'` (`module_gen.py:2574`) — a hand-written correction for
  exactly this field, in a sibling class. `MojoFunction`,
  `_MojoBoundComptimeFunction` and `MojoOverloadSet` were never given it, and
  `Parser` is not in the table at all, so all four fall through to whatever the
  derived pass concludes.
* **The derived pass's fallback is the receiver.** Whatever mints
  `MojoFunction._interp` decided `MojoFunction *`, which is `self`'s own type.
  `mojo/backend_gimple/module_gen.py:4246` skips a class in
  `_selfhost_hardcoded_struct_names` for the READ pass ("a read of a member this
  struct never ASSIGNS is a dynamic-attribute read ... it must reach the
  compiled `__getattr__`"), so the WRITE pass above it is where the mint
  happens, and it is what to instrument.

## Exact next step

1. Instrument one `selfhost` build to print, for every `struct_field_types[s.name][f]`
   write that is not one of the hand-declared entries, the `(s.name, f, ctype,
   source line)` tuple. Compare the four against the four source lines above;
   that names the pass in one run instead of by grep.
2. In that pass, make an unresolvable `self.X = <expr>` record the BOX
   (`int64_t`), which is `_selfhost_walk_stmts_for_self_assigns`'s own default
   (`_selfhost_merge_field(fields, _swfsa_member, _ct or 'int64_t')` in
   `mojo/backend_gimple/emit_funcs.py:1232`) and the same convention
   `_gscan_declare_global` uses for every container global. A receiver's own
   struct pointer is never a field's type unless the RHS really is that
   receiver.
3. Separately, add `_interp` to the three missing layouts beside
   `_MojoSortFn`'s, and check the rest of the table the way
   `tools/audit_selfhost_struct_fields.py` does for `fire_compiler.py`'s
   dataclasses — that tool only audits the AST dataclasses, and this is the
   first time the RUNTIME classes (`myinterpreter.py`'s `MojoFunction`,
   `MojoClass`, `Interpreter`, `Scope`, `Token`, ...) have needed it.
4. `Parser` needs the same treatment from the other side: `fire_compiler.py`'s
   `Parser` is a hand-written class whose fields are derived, and
   `self._comptime_rhs_failures: list = []` is the annotated-assignment case
   step 2 alone may not cover.