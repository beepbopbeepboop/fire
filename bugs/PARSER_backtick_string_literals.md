# PARSER: no support for backtick string literals (`` `...` ``)

## Symptom
Modular Mojo allows backtick-quoted strings for identifiers with special characters (e.g. `` `dotted.pkg` ``, `` `plain_mod.dot` ``). Our parser fails with "Expected NAME got STRING".

## Affected files
- mojo/test/mojo-parser/import/import_escaped_dotted.mojo
- mojo/test/mojo-parser/import/import_dotted_no_clash.mojo
- mojo/test/mojo-integration/package_rename.mojo

## Notes
- Backtick strings already partially handled in `_strip_inline_comment` (quoted-string awareness). Need lexer/parser support for backtick as a string/identifier delimiter.
EOF