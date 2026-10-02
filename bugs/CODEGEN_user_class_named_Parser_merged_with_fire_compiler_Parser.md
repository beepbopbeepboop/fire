# CODEGEN: a user class named `Parser` is MERGED with `fire_compiler.Parser` — one struct, wrong arity, no methods emitted

A program that defines its own class named `Parser` and imports it gets
every one of its methods resolved against **`fire_compiler.Parser`** — an
unrelated class in this compiler's own source, with a different `__init__`
signature. The build dies with a mix of arity and undefined-symbol errors
that name a class the user never wrote.

Root-caused to two independent defects, both whole-transitive-tree and
name-keyed tables colliding on the bare name `Parser`.

## Repro (two files, measured)

`.tmp/pc2/pkg/other.py`:

```python
class Parser:
    def __init__(self, tokens):
        self.toks = tokens

    def peek(self):
        return self.toks[0]
```

`.tmp/pc2/pkg/mine.py`:

```python
from .other import Parser

def use(src, filename='x'):
    psr = Parser(src)
    if not psr.peek():
        return None
    return psr

print(len(use([1, 2])))
```

```
$ gcc -fgimple -Iruntime -fsyntax-only <generated.c> runtime/fire_runtime.c
other.py:4:1: error: non-trivial conversion in 'var_decl'
other.py:7:1: error: non-trivial conversion in 'component_ref'
mine.py:6:9: error: implicit declaration of function 'fire_compiler_Parser_peek';
                          did you mean 'fire_compiler_Parser__parse_expr'?
```

Measured on `6b9b6b18`, `do_imports=True`.

## Defect 1 — the two struct layouts are MERGED into one C struct

The generated preamble:

```c
typedef struct Parser {
  int64_t __mojo_type_id;
  MojoList * _tok;          /* fire_compiler.Parser */
  int64_t _pos;             /* fire_compiler.Parser */
  char * _filename;         /* fire_compiler.Parser */
  MojoList * _pending_decs;  /* fire_compiler.Parser */
  MojoSet * _known_traits;   /* fire_compiler.Parser */
  struct Parser * toks;     /* the USER's Parser */
} Parser;
```

Verified by instrumenting `_compile_imported_module`: compiling module
`.other` changed `gen.struct_field_types['Parser']` from the self-host
layout to `{_filename, _known_traits, _pending_decs, _pos, _tok, toks}` —
the user's field ADDED to the existing ones rather than replacing them.
`struct_field_types` is keyed by BARE STRUCT NAME across every module
compiled in one run, and the class-registration path writes into an entry
that is already present.

Note this is WORSE than a wrong-slot read: the user's `Parser` object
occupies a C struct laid out for a different class, so every field access
is at the wrong offset.

## Defect 2 — no method symbols are emitted for the user's `Parser` at all

The generated unit contains the struct but ZERO `Parser_*` method symbols
(grep for `^\w*Parser_\w+` over the emitted C: no hits). Every call site
therefore emits a reference to a symbol nothing defines, which gcc reports
as `implicit declaration of function 'fire_compiler_Parser_peek'`.

`_imported_struct_home['Parser'] = 'fire_compiler'` is a PLAIN ASSIGN
(`module_gen.py:2276`, inside `gen_module_impl`, NOT gated by the
`_is_selfhost_file` check its sibling struct-layout hardcodes at
`:2141` use), so it overwrites whatever the module scanner registered and
forces every `Parser` method qualifier to `fire_compiler`. The comment
above it states the intent correctly — "modules that hardcode the struct
layout above but don't directly `from fire_compiler import Parser`" — i.e.
it is a FALLBACK for the self-host closure, not a claim about every struct
named `Parser` in every program. The assignment just does not behave like
one. Its own siblings (`Span`, `Scope`, `Interpreter`, ...) are all
`_is_selfhost_file`-gated; this one is not.

`setdefault` at this site is necessary but demonstrately NOT sufficient:
measured on this tree, the scanner registers no `Parser` of its own for a
`fire_compiler.py` compile (`_imported_struct_home.get('Parser')` is `None`
after), so `setdefault` changes nothing in either direction here. Tried,
measured, reverted — recorded so the next session does not re-derive it.

## Real instance: Tools/cases_generator

`analyzer.py`'s own errors are a smaller story (see below), but its
transitive sibling `parser.py` shows the whole shape:

```
parser.py:48:3: error: too many arguments to function
                       'fire_compiler_Parser___init__'; expected 2, have 3
parser.py:52:10: error: implicit declaration of function
                       'fire_compiler_Parser_next'; did you mean ...?
parser.py:58:10: error: implicit declaration of function
                       'fire_compiler_Parser_getpos'; ...
parser.py:67:3:  error: implicit declaration of function
                       'fire_compiler_Parser_setpos'; ...
parser.py:68:10: error: implicit declaration of function
                       'fire_compiler_Parser_peek'; ...
parser.py:72:10: error: implicit declaration of function
                       'fire_compiler_Parser_definition'; ...
parser.py:75:10: error: implicit declaration of function
                       'fire_compiler_Parser_eof'; ...
parser.py:74:3:  error: implicit declaration of function
                       'fire_compiler_Parser_backup'; ...
```

`Cases/cases_generator/parsing.py:333` declares `class Parser(PLexer)` —
one `__init__` parameter, inherited from the base class — and `parser.py:1`
re-exports it (`from parsing import (... Parser ...)`), so the class crosses
a MODULE boundary before use. `fire_compiler.py:2869` declares its own
`class Parser` with `def __init__(self, tokens: list[Token])`. Same bare
name, two classes, and the re-export means neither the definition module's
name nor the importing module's is enough to disambiguate.

## Next step, in order

The name `Parser` colliding with a self-host class is not itself the bug —
a user is entitled to call a class anything. Both defects are instances of
one structural rule that is applied to structs by BARE NAME:

1. **`struct_field_types` must not merge two same-named classes.** The
   class-registration path needs the same module-scoped discipline the
   module-globals fix applied to `_global_var_types`
   (`bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer_info.md` — see
   `_own_global_var_types` / `_own_overlay_global_ctype`, and the
   `_module_global_field_type` per-module lookup added alongside). There
   is no `_own_struct_field_types` equivalent; the field map is the last
   bare-name-keyed table in this path without one.
2. **`_imported_struct_home` needs the `_is_selfhost_file` gate** the
   sibling hardcodes already have, so a user's `Parser` is never
   qualified `fire_compiler_`. Necessary on its own for correctness even
   once (1) lands — they are independent tables.

Neither is small. (1) is the real one; (2) alone leaves the merged layout,
and (1) alone leaves the wrong qualifier.

## NOT this: `analyzer.py`'s own remaining error

`analyzer.py:194:10: error: expected expression before '(' token` looked like
a `", ".join([str(c) for c in self.caches])` lowering bug and is NOT.
Compiling `analyzer.py` directly with `do_imports=True` and with
`do_imports=False` both produce a `Uop_dump` that is entirely correct —
`mojo_list_get_int` → `CacheEntry___str__` → `mojo_list_append_str` →
`mojo_str_join`, with every temp correctly typed. The build only fails
because `fire.py build` compiles the whole `Tools/cases_generator`
sibling set into one unit, where `parser.py`'s `Parser` errors above are
present. Recorded here because it is the observable head of the
`analyzer.py` doc's error list and belongs to this root cause, not to
`bugs/COMPILE_FAIL_Tools_cases_generator_analyzer.md`'s own
(`non-trivial conversion in 'var_decl'` on the `char * tkn` loop variable,
which is the list-element-typing family that doc already names).