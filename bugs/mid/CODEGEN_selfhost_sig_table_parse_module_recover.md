# CODEGEN: the self-host signature tables still declare `parse_module(self)`

**Found:** 2026-11-12, while running `test_gimple.py` for the `stdlib-syntax`
doc's quick test. Re-measured on master after the 2026-11-12 stdlib restore:
`test_gimple.py` has this one failure (453 passed, 1 failed, 1 skipped — the skip
is `a_program_written_inside_the_checkout_is_not_the_compiler`, which needs
TMPDIR inside the checkout).

```
FAIL  handwritten_selfhost_signature_tables_match_the_source:
  Parser_parse_module: table declares 1 C parameter(s), the source takes 2
  (['self', 'recover']) — a DEFAULTED parameter still occupies a C parameter slot
```

## Cause

`fire_compiler.Parser.parse_module` gained a second parameter in `4234078f8`
("parser: recover at module scope after malformed declarations"), landed on
master by merge `82e5cded0`. One of the two hand-written C signature tables was
not updated with it:

- `gimple_codegen.py:508` — `_SELFHOST_SIGS['Parser_parse_module']` is
  `('MojoList *', ['Parser *'], 'fire_compiler')`
- `gimple_codegen.py:3889` — `_LIBC_SIGS['Parser_parse_module']` is
  `('MojoList *', ['Parser *'])` (the `test_gimple.py` case reads
  `_SELFHOST_SIGS`; the second table has no checker at all, which is why both
  must be fixed together)

The definition is `def parse_module(self, recover: bool = False) -> list:`.
A defaulted parameter still occupies a C parameter slot: the self-host
materializes it at every call site, so the forward declaration
`MojoList *Parser_parse_module(Parser *)` disagrees with the definition
`MojoList *Parser_parse_module(Parser *, bool)`. In a self-host closure that is
gcc's "conflicting types for 'Parser_parse_module'" once per importing module,
plus `-Wint-conversion` at every call site — unrecoverable, and invisible to
every check except this signature test (the light landing gate only runs
`stdlib-syntax`; `gimple`/`bootstrap` are not in it).

## What was run

    python3 test_gimple.py        # the case above is the one failure

## Done when

The named test passes:

    python3 test_gimple.py

with `PASS  handwritten_selfhost_signature_tables_match_the_source`, and the
stdlib tests are unchanged.

## Next step

Add the 2nd parameter to **both** tables at the C type the codegen infers for
`recover: bool` (check what `_ctype_for` emits for a `bool` parameter in a
self-host declaration — `test_gimple.py`'s case only checks arity, but the
declaration must match the definition's real C type, or the bootstrap fails at
the prototype instead). Update both `_SELFHOST_SIGS` (line 508) and
`_LIBC_SIGS` (line 3889) in `gimple_codegen.py`. `test_gimple.py` is the quick
test; the definitive check is the self-host closure (`bootstrap-stage1-*`),
which is the integrator's to run.
