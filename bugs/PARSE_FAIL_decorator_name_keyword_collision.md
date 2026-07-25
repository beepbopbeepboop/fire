# PARSE_FAIL: a decorator name (`@NAME`) that collides with a Mojo keyword fails to parse

## Status
**Fixed** (2026-07-25)

## Fix
`mojo_compiler.py`'s `_parse_stmt` decorator-parsing code (~line 1302-1313)
read the decorator name — and each component of a dotted decorator name —
via `self._expect("NAME")`, which rejects any keyword-shaped token even
though decorator names are ordinary Python identifiers. Replaced the
hand-rolled `dec_name = str(self._expect("NAME").value)` + dotted-`.`-loop
with a single call to the existing `self._parse_dotted_name()` helper
(already used for `except mod.Error:` types), which internally reads every
component via `self._ident()` — the same keyword-accepting helper used by
the earlier `ref`-keyword fix (`_parse_from_import`). This both fixes the
single-name case (`@enum(Foo)`) and the dotted case, including a keyword
appearing in the *middle* of the chain (`@a.enum.b`), for free — dotted
decorators were already supported by this parser, so no new grammar
support was added, just made keyword-tolerant like the rest of the file.

Also dropped the now-unneeded `str()` wrapper/comment about self-hosted
codegen inferring `dec_name` as `int64_t` — `_parse_dotted_name()` is
annotated `-> str`, so the self-hosted codegen already infers the correct
type from its signature, same as its other call sites.

## Verification
- Reproduced the bug doc's exact repro (`@enum(Foo)` on a `struct Bar`)
  with `python3 mojo.py run test.mojo`: previously
  `SyntaxError: Expected NAME got KW('enum')`, now parses and runs cleanly
  (no output, no error — decorator call succeeds since `deco` returns `cls`
  unchanged).
- Ordinary decorators (non-keyword name) still work: verified `@mydeco`
  applied to a `def` runs unchanged.
- Direct parser-level test confirmed a keyword in the *middle* of a dotted
  decorator chain also now parses: `@a.enum.b` on a `def` parses to
  `decorators == ['a.enum.b']` (previously would have failed at the first
  `_expect("NAME")` in the dotted loop, same class of bug).
- `python3 test_gimple.py`: 160 passed, 0 failed.
- `python3 test_module_cache.py`: 58 passed, 0 failed.
- `make check-selfhost`: passes ("self-host compiles + links clean").
- From-scratch stdlib dylib build (`rm -f build/libmojostdlib.dylib`,
  rebuild via `build_stdlib_dylib.build_stdlib(jobs=8)`): skip count is
  `0` both before and after the change (full dylib built successfully,
  4.2MB, no skip/fail/error lines beyond routine "drop stale export"
  linker-pruning notices which are expected/unrelated output).

## Reproduction
```mojo
def deco(cls):
    return cls

struct Foo:
    var x: Int

var enum = deco

@enum(Foo)
struct Bar:
    var y: Int
```
Run: `python3 mojo.py run test.mojo`

## Actual Behavior
```
SyntaxError: test.mojo:9:1: Expected NAME got KW('enum')
```
`_parse_stmt`'s decorator handling (`mojo_compiler.py:1459`,
`dec_name = str(self._expect("NAME").value)`) requires the token right
after `@` to be a real `NAME`-kind token — it rejects any decorator whose
name happens to lex as a Mojo keyword (`enum`, `struct`, `fn`, `ref`, ...),
even though `enum`/`struct`/etc. are all perfectly ordinary Python
identifiers with no special meaning in real Python (this dialect just
happens to also use them as its own keywords). Note this is narrower than
the general "keyword used as an identifier at statement start" bug class
(see `bugs/PARSE_FAIL_fn_keyword_as_identifier.md`,
`bugs/PARSE_FAIL_struct_keyword_as_identifier.md` in this same directory) —
this is a single, specific grammar position (right after `@`), the same
narrow shape as the much earlier `bugs/PARSE_FAIL_ref_keyword.md` fix
(`from X import ref`), not a statement-start disambiguation problem.

## Expected Behavior
`@enum(...)`/`@struct.something`/any decorator whose name is
keyword-shaped in this dialect but is a legitimate Python identifier
elsewhere should parse like any other decorator.

## Real-world impact
Confirmed via real CPython 3.14 stdlib source: `Lib/test/test_enum.py:245`,
`@enum.global_enum` (a real decorator from the `enum` standard library
module, applied to a class in that file's own test code).

## Suggested approach
This is a narrow, single-position fix — follow the exact same pattern
already used for the earlier `ref`-keyword fix (`_parse_from_import` reading
names via `_ident()`, which accepts keyword-shaped tokens, instead of
`_expect("NAME")`). Change the decorator-name read at `_parse_stmt`
(`mojo_compiler.py:1459`) from `self._expect("NAME")` to `self._ident()` (or
whatever this codebase's established "read a name, accepting a
keyword-shaped token" helper is called — check what `_parse_dotted_name`
and the `ref`/`fn`/`struct` fixes already established and reuse it exactly,
rather than writing new logic). Check whether a DOTTED decorator name
(`@enum.global_enum`, i.e. `NAME (DOT NAME)*` after the `@`) is already
supported for the ordinary case, and if so make sure the keyword-accepting
version still composes correctly with the dotted-name parsing (each
component of the dotted chain may itself need keyword-acceptance, not just
the first token).

## Files Likely Affected
- `mojo_compiler.py` — `_parse_stmt`'s decorator-parsing code (~line 1459),
  specifically the `dec_name = str(self._expect("NAME").value)` line and
  whatever follows it for a dotted/parameterized decorator name.
