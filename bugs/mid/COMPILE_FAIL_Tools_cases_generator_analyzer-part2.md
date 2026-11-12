# COMPILE_FAIL_Tools_cases_generator_analyzer-part2: a sibling class named like a compiler AST node keeps its own layout

Part 2 of 4 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`.

## Goal

When a compiled program imports a sibling module whose class has the same bare
name as one of this compiler's own AST node classes (`IfStmt`, `ForStmt`,
`WhileStmt`, `Parser`, ...), the generated C must define **the sibling's**
struct — its own fields, its own `_alloc_`/`_init_` and its own method
signatures — instead of the compiler's pre-seeded AST layout. This is the
blocker that currently produces 22 of `analyzer.py`'s 27 gcc errors.

## Current state (measured 2026-11-11, HEAD `d210765a2`)

```sh
mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/cases_generator .tmp/ca/
python3 tools/memslot.py --gb 8 --label analyzer-build -- \
    python3 fire.py build -o .tmp/ca/analyzer-bin .tmp/ca/cases_generator/analyzer.py
```

Exit 1 after ~15 s. `grep -o 'cases_generator/[a-z_]*\.py:[0-9]*:[0-9]*: error'`
groups them as:

| reported file | count | actual owner |
|---|---|---|
| `parsing.py` | 22 | the sibling module's `IfStmt`/`ForStmt`/`WhileStmt` methods |
| `plexer.py` | 3 | **`#line` misattribution**: the source `plexer.py` is 124 lines, so `plexer.py:292/316/586` are really emitted while the line map named `plexer.py`; the statements are `parsing.py`'s constructors |
| `analyzer.py` | 2 | part3 (the parenthesized ternary), not this part |

Representative errors:

```
parsing.py:102:13: error: 'IfStmt' has no member named 'if_'
parsing.py:105:14: error: 'IfStmt' has no member named 'body'
parsing.py:106:14: error: 'IfStmt' has no member named 'else_'
parsing.py:135:13: error: 'ForStmt' has no member named 'for_'
parsing.py:136:13: error: 'ForStmt' has no member named 'header'
parsing.py:157:13: error: 'WhileStmt' has no member named 'while_'
parsing.py:114:1:  error: non-trivial conversion in 'component_ref'
```

The generated `.ci` shows why. Its `IfStmt` typedef is this compiler's own AST
layout, not `parsing.py`'s:

```c
typedef struct IfStmt {
  int64_t __mojo_type_id;
  int64_t condition;
  MojoList * then_body;
  MojoList * elifs;
  MojoList * else_body;
  int64_t line;
  int64_t col;
} IfStmt;
```

while the sibling's methods are emitted against the sibling's fields:

```c
void __GIMPLE parsing_IfStmt_print (IfStmt * self, CWriter * out)
{
  ...
  _t1 = self->if_;     /* no such member in the typedef above */
```

`parsing.py`'s own `IfStmt` declares `if_: lx.Token`, `condition:
list[lx.Token]`, `body: Stmt`, `else_: lx.Token | None`, `else_body: Stmt |
None`.

This is **import-side only**. The same class written in the root module works:
`.tmp/collision_probe.py` (`class IfStmt` with `if_`/`body`, `fire.py build`,
then run) prints `3 4`. The defect appears when the class arrives through
`do_imports`/the import closure.

### Code paths to start from

* Pre-seeded compiler layouts, installed into `struct_field_types` in
  `GimpleGen.__init__`: `Parser` at `mojo/backend_gimple/module_gen.py:6129`,
  `IfStmt` at `:6270`, `WhileStmt` at `:6278`, `ForStmt` at `:6285` (plus the
  rest of the AST table around them). These entries have no owner and no home.
* The module-qualified identity pass at `module_gen.py:7433-7507`
  (`_struct_cname_by_id` / `_struct_name_owner`). It qualifies a loser only for
  a genuine **cross-module** collision, and treats a missing home on either side
  as a same-file redefinition:
  `if not _shome or not _ohome or _shome == _ohome: continue`.
* The struct field pass at `module_gen.py:7540-7600`, which writes a struct's
  fields under the cname only when `_struct_name_owner.get(s.name) is s`, and
  only here for fields **without** a type annotation; annotated fields come from
  the earlier layout seed/merge.
* Relative to this doc's earlier entry, the `Parser`-specific arity errors are
  gone. What remains is the shared-bare-name **layout** collision on the other
  AST names.

The exact owner that wins the bare name in the combined unit is the first thing
to print, not to guess: in a scratch debug run, log
`_struct_name_owner.get('IfStmt')`, `id()` of that value,
`_struct_home_by_id` for both operands, and `_struct_cname_by_id` for the
`parsing.IfStmt` node. The measured facts above constrain the answer but do not
by themselves prove whether the pre-seeded dict entry, a compiler-side
`StructDef`, or the imported module's own `StructDef` is the winner.

## Plan

1. **Diagnose first** (cheap, in a throwaway `.tmp` run): instrument the identity
   pass for the repro below and record which object owns `IfStmt`, what home it
   has, and what cname the imported `StructDef` receives. That answer selects
   between the two fixes below; do not apply both.
2. **Preferred fix — the pre-seeded AST layouts are not peer modules.** Treat
   the compiler's own AST layouts as belonging to the compiler's home (a
   sentinel such as `'fire_compiler'`, stored in the same
   `_struct_home_by_id`/owner tables the pass already reads). Then a sibling
   module's `IfStmt` is a genuine cross-module collision and the existing pass
   gives it `parsing_IfStmt` (or the sanitized-home spelling) and its own field
   table. The stored compiler layouts are unchanged, so the self-host closure's
   struct set and the `_MOJO_STUB_` guard names stay as they are (a
   non-colliding name still gets the bare name byte-for-byte).
3. **If the diagnostic shows the imported `StructDef` never reaches the identity
   pass**, the fix belongs in the import-merge layer instead: the imported
   module's field table must not be shadowed by an already-installed pre-seed of
   the same bare name; merge it under the module-qualified cname. Keep this
   single-layer, not a second name-keyed table.
4. Whatever the layer, make **one** identity decision reach all consumers:
   emitted `typedef`, `_alloc_<cname>`, `_init_<cname>`,
   `struct_field_types[cname]`, `struct_boxed_fields`, and
   `_resolve_struct_cname` for method signatures. A fix that qualifies the
   typedef but leaves a bare `IfStmt *` in a method signature just moves the
   gcc error.
5. **Tests** as below. The fixture must go through `do_imports=True`; a
   single-file fixture passes today and proves nothing.

## Acceptance

* The new fixture (below) emits a `typedef struct <user-cname> IfStmt` with
  `if_`, `body`, `else_`, `else_body` and no `then_body`/`elifs`, and
  `gcc -fgimple -fsyntax-only` accepts the generated C. Today it rejects it with
  `'IfStmt' has no member named 'if_'`.
* In the analyzer build, all `has no member named` errors in `parsing.py` and
  the `assignment ... from 'MojoList *'` constructor errors are gone. The
  remaining error is part3's `analyzer.py:194`.
* Self-host is not regressed: `python3 test_gimple.py` passes, and the
  integrator's `make gate` (bootstrap's stage1 == stage2 == stage3 comparison)
  is the heavy confirmation. Do not run the whole-closure/bootstrap chain in
  the part's own round.

## Done when

`python3 test_sibling_ast_name_collision.py` (new file) exits 0.

The test builds a temporary sibling package:

```python
# parsing.py
class IfStmt:
    def __init__(self, if_: int, body: int):
        self.if_ = if_
        self.body = body
    def show(self) -> None:
        print(self.if_, self.body)

# parser.py
from parsing import IfStmt

# main.py
import parser
parser.IfStmt(3, 4).show()
```

puts the directory on `sys.path`, calls
`gimple_codegen.compile_to_gimple(main_src, do_imports=True, filename=...)` and
asserts (a) the `IfStmt` typedef carries the user's fields, (b) the emitted C
compiles under `gcc -fgimple -fsyntax-only`. On the current tree (a) fails and
(b) prints `'IfStmt' has no member named 'if_'`; measured by running the same
`compile_to_gimple(..., do_imports=True)` call directly on this fixture
(2026-11-11).

## Out of scope

* Link-mode sibling resolution (`fire.py build`'s link mode stubbing
  `parser.*`/`lexer.*`): a separate recorded blocker; this part is the
  `do_imports`/inline path the analyzer build takes.
* The parenthesized-ternary error at `analyzer.py:194` (part3) and the
  class-pattern binding bug (part1).
* Making `fire.py run` import sibling modules from the script's directory.
