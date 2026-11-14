# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `work/fix-merge-bug-diagnostics-trait-conformance-part6-4` (task `fix-merge-bug-diagnostics-trait-conformance-part6-4`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `work/fix-merge-bug-diagnostics-trait-conformance-part6-4`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

Failing files at the time:
- `std/utils/variant.mojo`

## Status (2026-11-14)

Root cause found and fixed. The red is on `work/fix-merge-…-part6-4` only: that
branch adds the declaration-time trait-requirement check, and the check
compared a required method's signature TEXTUALLY. `std/utils/variant.mojo`'s
`trait _NicheStorage` declares `def as_uninit[T: AnyType](ref self) -> …` and
`_DefaultNicheStorage` implements it as `def as_uninit[U: AnyType](ref self) ->
…`; a method's own bracket parameters are local names, so those are the same
signature, but the differing spellings read as "signature mismatch" and the
module was rejected with `'_DefaultNicheStorage' does not implement all
requirements for '_NicheStorage'`.

`elaborate._method_sig` now alpha-renames a method's own bracket parameters
(`_m0`, `_m1`, …) before the comparison, which is where both the pre-existing
`check_conformance` and the branch's declaration-time caller read signatures
from. `Self.T` (the struct's parameter) is deliberately not renamed. Master
itself has no failing file today; the fix is what makes the branch's merge
green. Reproduced and re-verified with a COLD CAS (`GMOJO_HOME` in `.tmp`), so
neither verdict is a cache replay: branch `elaborate.py` fails
`std/utils/variant.mojo`, the same file with this `_method_sig` change
transpiles clean (`cg_hit=False gcc_hit=False`).

## Done when

- `python3 test_stdlib_syntax_variant.py` (the `stdlib-syntax` pin for this
  file) passes.
- `python3 test_trait_generic_method_alpha_rename.py` passes: the
  `_NicheStorage`/`_DefaultNicheStorage` shape conforms, a genuinely different
  return type is still rejected, and `Self.T` survives un-renamed.
