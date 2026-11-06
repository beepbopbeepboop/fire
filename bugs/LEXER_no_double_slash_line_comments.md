# LEXER: no support for `//` line comments

## Symptom
Modular Mojo uses `//` for line comments (LLVM-style). Our lexer only recognises `#`. Any file containing `//` fails to parse.

## Repro
Any modular test file with `// RUN:` or `// CHECK:` directives (all of them).

## Notes
- `#` is supported (`_strip_inline_comment`, `py_tokenize`).
- Need to treat `//` (and possibly `///` doc comments) as end-of-line comments in `py_tokenize` and in `_strip_inline_comment`.
- This is foundational: without it, no modular test file can even be parsed by our compiler.

## Status
Open. First step: add `//` to comment-stripping in fire_compiler.py.
EOF