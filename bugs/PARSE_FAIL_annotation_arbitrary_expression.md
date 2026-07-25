# PARSE_FAIL: annotation position occupied by an arbitrary (non-type-shaped) expression

**Status: FIXED**

## Symptom

```mojo
def foo(a) -> {}:
    pass
foo(1)
print("ok")
```

failed with:

```
SyntaxError: ...: Expected NAME or KW got LBRACE('{')
```

A second manifestation, a list-literal-shaped annotation:

```mojo
def bar():
    var2: [Int, String] = 1
```

failed the same way (`Expected NAME or KW got LBRACKET('[')`).

## Root cause

`_parse_type_ann_inner` in `mojo_compiler.py` builds a type annotation as a
plain STRING by consuming NAME/KW tokens, dotted names (`.`), and
bracket-nested generic type args (`Name[Args]`). It had no fallback for an
annotation position occupied by something that doesn't look like a type name
at all — real Python's (and Mojo's) grammar syntactically permits an
arbitrary expression in an annotation position even though it's semantically
nonsensical (e.g. an empty dict literal `{}` as a return type, or a
list-literal-shaped thing `[Int, String]` as a variable annotation). The
final `else` branch unconditionally raised `SyntaxError` for any token that
wasn't NAME/KW.

## Investigation: is the annotation string meaningfully consumed downstream?

Before fixing, traced every consumer of `_parse_type_ann`/`_parse_type_ann_inner`'s
returned string:

- `gimple_codegen.py`'s `_mojo_type(ann)` and `_resolve_type(ann)` — the main
  codegen consumers. Both do simple `'[' in ann` / `.split('[', 1)` /
  `_TYPE_MAP.get(ann)` lookups. An annotation string that doesn't match any
  known shape or name falls through harmlessly to the `int64_t` default (or,
  for `_resolve_type`, just returns whatever `_mojo_type` produces). No
  indexing or parsing pattern anywhere assumes the string is well-formed
  type syntax beyond "does it start with a known base name" checks, which
  simply fail (return False/None) for nonsense text.
- `gimple_codegen.py`'s local-field-type inference (`_scan_body_for_local_field_access`,
  around line 14969) does a dict-membership check (`ann in self.struct_field_types`)
  — safe for any string.
- `myinterpreter.py` — only a handful of references, none that parse the
  annotation string further; it's treated as an opaque label except where
  it matches a known type name exactly.

Conclusion: the annotation string is **never structurally re-parsed**
downstream in a way that would crash or misbehave on non-type-shaped text —
every consumer either matches known type names/shapes exactly or falls back
to a safe default. This confirmed the narrow "just consume opaque balanced
token text and move on" fallback (as opposed to building a real
expression-AST fallback) is safe.

## Fix

Extended `_parse_type_ann_inner`'s final `else` branch (previously an
unconditional `raise SyntaxError`) to handle three cases instead of always
raising:

1. `LBRACKET` — reuses `_capture_bracketed_text` (the bracket-depth-aware
   helper added by the subscript-target fix, commit `8cd5d6c`) to consume a
   balanced `[...]` and returns it as opaque text, e.g. `"[Int, String]"`.
2. `LBRACE` — new inline balanced-`{...}` capture (mirroring the existing
   balanced-paren capture already present earlier in the same function),
   returns e.g. `"{}"`.
3. Anything else — consumes the single stray token as opaque raw text.

No general expression-AST fallback was built; the annotation string
produced by these fallback paths carries no semantic meaning, matching the
existing convention that unrecognized annotation strings are inert
placeholders as far as codegen/interpretation is concerned.

## Verification

- Both repros above now parse and run successfully (`python3 mojo.py run`
  produces `ok` for both), producing an opaque annotation string that is
  never dereferenced meaningfully.
- Broad regression check of ordinary annotations (byte-identical behavior
  confirmed): `var x: Int`, `def f(a: String, b: Int = 5) -> Bool`, generic
  annotations (`List[Int]`, `UnsafePointer[Int]`, `Optional[Int]`), dotted
  annotations (`Foo.Bar`), MLIR backtick/dotted types
  (`__mlir_type.i1`), forward-reference string annotations (`"ForwardRef"`).
  All parse and run identically to before the change.
- `python3 test_gimple.py`: 161 passed, 0 failed.
- `python3 test_module_cache.py`: 64 passed, 0 failed.
- `make check-selfhost`: passes clean (mojo.py compiling its own source).
- From-scratch stdlib dylib build
  (`rm -f build/libmojostdlib.dylib && python3 -c "import build_stdlib_dylib as bsd; bsd.build_stdlib(jobs=8)"`):
  **0 skips** — no regression from the pre-change baseline of every stdlib
  file compiling clean.

## Files changed

- `mojo_compiler.py` — `_parse_type_ann_inner`'s final fallback branch.
