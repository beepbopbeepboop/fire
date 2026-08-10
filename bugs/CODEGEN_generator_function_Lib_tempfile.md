# CODEGEN_generator_function: Lib/tempfile.py

## Status (updated 2026-08-09)

Re-verified again against current master with a fresh real rebuild
(`MOJO_DEBUG=1 python3 mojo.py build .../Lib/tempfile.py`, real
`gcc-mp-15`/`g++-mp-15` via `mojo.py`'s own resolution). Classification
UNCHANGED: **NOT a generator-codegen-cluster failure**.
`_TemporaryFileWrapper.__iter__` (`for line in self.file: yield line`,
line 556) shows no "not eligible" refusal in `MOJO_DEBUG=1` output and
does not appear in the error list — still compiles cleanly through the
coroutine path.

The exact same 13 errors reproduce byte-for-byte:
```
tempfile.py:64:17:   error: expected identifier before numeric constant
tempfile.py:200:24:  error: expected identifier before numeric constant
tempfile.py:250:24:  error: expected identifier before numeric constant
tempfile.py:376:24:  error: expected identifier before numeric constant
tempfile.py:423:23:  error: expected identifier before numeric constant
tempfile.py:496:46:  error: stray '\' in program
tempfile.py:609:6:   error: request for member 'name' in something not a structure or union
tempfile.py:668:6:   error: request for member 'name' in something not a structure or union
tempfile.py:703:6:   error: request for member 'name' in something not a structure or union
tempfile.py:4732:7:  error: expected identifier or '(' before numeric constant
tempfile.py:4755:4:  error: expected identifier before numeric constant
tempfile.py:4756:3:  error: expected '}' before '.' token
```
(one fewer distinct line than "13 total" implied previously — 12 error
lines; the miscount doesn't change the classification.)

**Root-caused the `stray '\'` / textwrap.py-transitive bug precisely**
(per this session's brief to pin this recurring cross-file pattern down
further, without fixing it). It is NOT a tokenizer bug at all, and NOT
really "in textwrap.py" — mojo_compiler.py's own `py_tokenize` correctly
tokenizes every raw-string construct in textwrap.py, verified directly
(`mc.py_tokenize()` on the real file and on isolated multi-line
raw-string-concatenation snippets copied verbatim from it, e.g. the
`sentence_end_re = re.compile(r'[a-z]' r'[\.\!\?]' r'[\"\']?' r'\z')`
implicit-concatenation shape at textwrap.py:107-110 — all tokenize
correctly).

The real bug is in `gimple_codegen.py`'s **class-body string-attribute
initializer emission**, which — unlike every other string-literal-to-C
lowering path in this file — does NOT run the value through the
existing shared `_c_escape()` helper (`gimple_codegen.py:3106`) before
splicing it into a C string literal. Two call sites, both in the
class-attribute-globals section of `gen_module` (the pass that builds
`_class_attr_inits`, used for `emit_struct_defs`/main-module code, see
`_mojo_classattr_init`):
```python
# gimple_codegen.py:33521-33522 (class-body SET literal string elements)
if isinstance(elt, StringLiteral):
    inits.append(f'  mojo_set_add_str ({mangled}, "{elt.value}");')
...
# gimple_codegen.py:33530-33532 (plain class-body string attribute)
elif isinstance(v, StringLiteral):
    ctype = 'char *'
    class_attr_inits.append(f'  {mangled} = "{v.value}";')
```
Both should read `_c_escape(elt.value)` / `_c_escape(v.value)` (exactly
like every other string-emission site in this file already does), but
don't. Any class-body string attribute whose value contains a literal
`"` character breaks the generated C string literal early; if raw
content shortly after the embedded `"` also contains a `\` (e.g. an
escaped-quote `\'` from a raw-string regex fragment), that backslash
ends up OUTSIDE any string context in the emitted C — hence gcc's
"stray '\' in program", reported at whatever line/column gcc's own
recovery lands on, which can be arbitrarily far downstream in the same
concatenated translation unit (explaining why this has previously
appeared attributed to unrelated files/symbols — codecs.py, ipaddress.py,
enum.py — compiled alongside the true trigger).

**Confirmed exact trigger in textwrap.py**: `TextWrapper.word_punct =
r'[\w!"\'&.,?]'` (textwrap.py:74) — a `TextWrapper` class-body string
attribute containing an embedded `"`. Root-caused via a minimal,
isolated, from-scratch repro (no textwrap.py/tempfile.py involved at
all):
```python
class TW:
    a = '"'          # <-- alone, this already breaks the build
def main(): print("ok")
main()
```
compiled standalone with `mojo.py build` and reproduces the identical
"missing terminating \" character" / "expected ';' before '}' token"
failure signature. Adding a trailing backslash-quote sequence after the
embedded `"` (mirroring `word_punct`'s real `\'` fragment) upgrades the
same failure to the exact "stray '\' in program" signature seen in the
real build. In the real textwrap.py build, the corruption surfaces at
the very NEXT class-body attribute in source order after `word_punct`
(`letter = r'[^\d\W]'`, C symbol `_classattr_TextWrapper__letter`) —
consistent with `word_punct`'s own init line being the one that actually
breaks the C parse.

This is a genuinely narrow fix (two call sites, wrap in the
already-shared `_c_escape()` helper) — but per this session's scope,
**not attempted here**; left for a dedicated fix pass to act on directly
using the line numbers/call sites above. No code change made in this
pass. The `expected identifier before numeric constant` family
(lines 64/200/250/376/423/4732/4755/4756) and the `request for member
'name'` family (lines 609/668/703, a `getattr(getattr(file, 'buffer',
file), 'raw', raw).name = ...` chained-getattr type-inference gap) were
NOT further investigated — out of scope for this generator-codegen pass,
unchanged from the prior note.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`_TemporaryFileWrapper.__iter__` still shows zero signal of a problem.
The `struct _threading_toplev`/etc. pattern is GONE (fixed by
`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s
"mechanism 2" landing, same fix confirmed across several files this
session) and the `stray '\'` textwrap.py tokenizer issue is also gone
from this file's current error list. Remaining errors (13 total, all
in tempfile.py's own non-generator code): repeated `expected identifier
before numeric constant` (lines 64/200/250/376/423, plus 2 more further
in) and `request for member 'name' in something not a structure or
union` (lines 609/668/703), plus one `stray '\'`/`expected ';' before
'_classattr_TextWrapper__letter'` at line 496 (the textwrap.py issue —
apparently not fully gone, just reduced). Not investigated further here
— out of scope for this generator-codegen cluster; the `expected
identifier before numeric constant` repeating at several near-identical
column offsets (24, 23, 17) looks like a real, possibly-narrow parser/
codegen bug (worth a dedicated look by whoever picks up a non-generator
pass on this file) but wasn't traced to a root cause in this session.

## Status (updated 2026-08-06, superseded above — module_toplev pattern since independently fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'_TemporaryFileCloser' does not name a type` .cpp error no
longer reproduces. (Note: this build took over an hour wall-clock —
by far the slowest in this cluster — consistent with, though far more
extreme than, the already-documented `bugs/hard/PERF_nested_module_
compile_walk_ast_quadratic_rescan.md` perf issue.) `tempfile.py`'s own
generator (`_TemporaryFileWrapper.__iter__`, `yield line`, line 556)
does not appear in the current error list and has no "not eligible"
refusal — it appears to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure.** Current
errors (100+) are dominated by two already-cross-referenced patterns:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (7th confirmed occurrence — `_threading_toplev`, `_pprint_toplev`,
  `_io_toplev`, `__py_warnings_toplev`, by far the largest count of any
  file in this cluster).
- The recurring `stray '\' in program` / `_classattr_TextWrapper__
  letter` textwrap.py tokenizer bug (5th occurrence, seen previously in
  codecs.py/ipaddress.py/enum.py's re-diagnoses).

Also several `expected identifier before numeric constant` and
`'MojoBoundMethod' has no member named '_closer'`/`request for member
'name' in something not a structure or union` errors, not investigated
further. None implicate tempfile.py's own generator.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tempfile.py
