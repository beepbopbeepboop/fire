# CODEGEN_generator_function: Lib/symtable.py

## Status (updated 2026-08-07, failure point now pinned down)

Re-verified against current master with a real, complete rebuild
(previous pass's "zero hard errors visible" was incomplete triage, not
an actual clean build — the earlier grep evidently missed matches). The
build DOES have real errors, confirming the classification below:
**still NOT a generator-codegen-cluster failure** — symtable.py's only
generator (`yield flagname`, line 302) still shows zero signal of any
problem (no "not eligible" refusal, doesn't appear in the error list).
symtable.py's own 2 real errors:

```
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:449:10: error: too many arguments to function 'mojo_open_file'; expected 1, have 2
/Users/mrs/net/Python-3.14.6/Lib/symtable.py:576:46: error: stray '\' in program
```

Both are already-known, unrelated-to-generators patterns recurring
elsewhere in this cluster this session: the `mojo_open_file` 2-arg-call
arity mismatch (also seen in `Lib/mailbox.py`'s and `Lib/ftplib.py`'s
current re-diagnoses) and the textwrap.py-transitive stray-backslash
tokenizer issue (also seen in `Lib/codecs.py`'s/`Lib/ipaddress.py`'s).
Not investigated further here — out of scope for this cluster.

Also noted in passing (not attributed to symtable.py specifically —
appears in the debug log without a file marker, likely from some OTHER
module in the transitive closure): `MOJO_DEBUG=1` prints occasional
`unknown expression lowered to 0: YieldExpr`/`YieldFromExpr` notes.
Flagged for whoever next investigates a real generator-shape gap to
check whether this indicates an actual silent-miscompile case (a
`yield`/`yield from` appearing somewhere this codegen's expression
lowering doesn't recognize as generator context, e.g. inside a nested
comprehension or lambda) — not chased down further in this pass since
it produced no attributable error for any file examined this session.

## Status (updated 2026-08-06, superseded above — this pass's "zero errors" was incomplete triage)

Re-diagnosed against current master (`2b0c4c5`) — the 2026-07-30
`'flagname' was not declared` .cpp error no longer reproduces.
`symtable.py` has one generator (`yield flagname`, line 302) — it does
NOT appear anywhere in a full `MOJO_DEBUG=1` build log (0 `error:` lines
in the entire ~144K-line output, only warnings; no "not eligible"
refusal naming it either): symtable.py's own generator appears to
compile cleanly through the coroutine path.

`mojo.py build` still exits non-zero, but the failure point wasn't
pinned down in this pass — the gcc/g++ compile stage(s) visible in the
log show zero hard errors, so the actual failure is presumably at a
LATER stage (link, or a companion-.cpp step not captured by this file's
grep-based triage) not yet isolated. This build is also unusually slow
(minutes) — consistent with the already-documented, unrelated
`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
perf issue for files with a moderately large transitive import graph,
not a new finding here.

**Classification: very likely NOT a generator-codegen-cluster failure**
(symtable.py's own generator shows zero signal of any problem), but the
true current failure point needs a cleaner re-run (e.g. capturing the
link step's own stderr separately) to state with full confidence. Left
open rather than marked fixed.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/symtable.py
