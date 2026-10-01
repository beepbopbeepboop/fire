# CENSUS: which `formal/hostmods` modules build, per backend — and the two reasons x86-64 has fewer of them than arm64

## Status

OPEN — and it is coverage data rather than one defect, so it is filed as the
thing it is: a table of what this backend's own path libraries can do on each
architecture, measured 2026-09-30 on `work/formal-argparse-kind` while fixing
`argparse.mojo`'s unannotated-callee refusal. The two failures it records are
in other people's claims (`construct:x86-64-dylib`, which is the dylib emitter
one) and are NOT fixed here.

Nothing in `bugs/` had this table. Every host module except `argparse` had been
assumed buildable on the strength of its own test, and `test_formal_hashlib.py`
is arm64-only by the same convention `test_formal_argparse.py` follows
(`bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md` is the stated
reason), so the difference between "arm64-only because of a dylib signing bug"
and "arm64-only because a function has 7 parameters" was not written down
anywhere.

## What was run

    # every host module, built AS A PROGRAM (nothing importing it), one cold CAS
    # per (file, backend) — a cached verdict from a previous version of the file
    # would answer the wrong question
    python3 tools/memslot.py --gb 8 --label hostmods-census -- python3 .tmp/census.py

which is `fire.py build --formal --no-prove --backend=<arch> -o … <module>` per
row, with `GMOJO_HOME` a fresh directory per row. 3.7 s for all 18 rows.

| module | arm64 | x86-64 |
|---|---|---|
| `formal/hostmods/argparse.mojo` | BUILD | FAIL (import) |
| `formal/hostmods/re.mojo` | BUILD | FAIL (import) |
| `formal/hostmods/sys.mojo` | BUILD | BUILD |
| `formal/hostmods/struct.mojo` | BUILD | BUILD |
| `formal/hostmods/time.mojo` | BUILD | BUILD |
| `formal/hostmods/hashlib.mojo` | BUILD | FAIL (arity) |
| `formal/hostmods/os/__init__.mojo` | BUILD | FAIL (import) |
| `formal/hostmods/os/_syscalls.mojo` | BUILD | BUILD |
| `formal/hostmods/os/path/__init__.mojo` | BUILD | FAIL (import) |

**Every module builds on arm64.** The x86-64 column is 4/9, and both reasons are
below. Note what "FAIL (import)" means precisely: `os/_syscalls.mojo` builds on
x86-64 *as a program* and fails *as a dylib*, so the four rows that import it
never reach their own bodies and are unmeasured rather than known-bad.

## Failure 1 — a module dylib that makes an extern call (4 rows) — ALREADY FILED

    build: argparse.mojo imports 'os._syscalls', which cannot be built either:
    _syscalls.mojo: …/cas/formal-imports/x86_64/os__syscalls.1b3b3178b7d6.x86_64.dylib:
    main executable failed strict validation

This is `bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md`, which
already quotes this exact dylib name and says the boundary is "a module DYLib on
x86-64 that makes an extern call". Not re-filed and not fixed: it is the x86-64
dylib emitter's, and it is why a whole tested module is arm64-only today.

The census adds one thing to it: **the mask.** `re.mojo` imports `os._syscalls`
too, and `re.mojo` has FIVE functions with more parameters than the x86-64 ABI
passes in registers (`sub` 7, `_subwalk` 8, `_emit` 7, `_gref` 7, `_subfill` 7),
so fixing the signing defect alone will not make `re.mojo` build on x86-64 — it
will replace this message with failure 2. Measured by counting parameters, NOT by
building: the import refusal happens first, so `re.mojo`'s own x86-64 build has
never been reached.

## Failure 2 — 7 parameters, 6 argument registers (1 row) — NEW

    build: b2_g: 7 parameters exceeds the 6 the formal x86-64 ABI passes in registers

Raised by `formal/x86_64_codegen.py:767` (and the twin at `:5012`), against
`formal/hostmods/hashlib.mojo:307`:

    def b2_g(v: Pointer[UInt8], a: int, b: int, c: int, d: int, …)   # 7

SysV x86-64 passes six integer arguments in registers (`formal/x86_64.py:65`:
`ARG_REGS = (RDI, RSI, RDX, RCX, R8, R9)`) and the stack after that; AArch64
passes eight (`formal/arm64_codegen.py:60`, `_ABI_ARG_REGS = 8`), which is why
this is invisible on arm64 and why the module has been healthy there. The
emitter's choice is to REFUSE rather than to spill, which is the same policy as
every other place this backend declines to lower something it could lower — the
refusal is right in the sense that a wrong spill would be worse, but the message
does not say what to do, and a module written for one backend has no reason to
know the other's limit.

Affected functions, by parameter count, over all nine modules:

    formal/hostmods/re.mojo:      sub(7)  _subwalk(8)  _emit(7)  _gref(7)  _subfill(7)
    formal/hostmods/hashlib.mojo: b2_g(7)  put6(8)

The next step, and it is the same shape as argparse's: **an argument can be
ANNOTATED as spilled**, if the emitter has an annotation for it — or the
function can be split so that the 7th argument rides in a pointer the caller
already has (`hashlib`'s `b2_round` takes three pointers and could take a
pointer to the extra word). Whichever it is, the annotation would have to be
honoured by BOTH backends, and arm64 would have to keep accepting a call whose
spilled argument the caller did not pass. Check
`bugs/FORMAL_per_export_contracts.md` and `doc/ABI.md` first: a spilled-argument
convention is an ABI fact, and it belongs in the manifest signature next to the
return type rather than in one emitter.

While that is not done, `hashlib` is arm64-only for a second, unrelated reason,
and that is the honest sentence for `test_formal_hashlib.py`'s docstring to say.

## The census itself, and the one number worth remembering

`formal/hostmods/os/__init__.mojo:61` states the convention this backend wants:
"EVERY FUNCTION HERE SAYS WHAT IT RETURNS … the annotation is what puts `char *`
in the module dylib's manifest signature". Annotations by module, from the
sources (this is what `string_compare_word_refusal`'s "an ANNOTATED callee" arm
keys on, `formal/model.py:2237`):

    formal/hostmods/os/_syscalls.mojo        52 defs   52 annotated
    formal/hostmods/os/__init__.mojo          34 defs   34 annotated
    formal/hostmods/sys.mojo                  21 defs   21 annotated
    formal/hostmods/re.mojo                  120 defs  102 annotated
    formal/hostmods/os/path/__init__.mojo     33 defs   29 annotated
    formal/hostmods/hashlib.mojo              34 defs   29 annotated
    formal/hostmods/time.mojo                 22 defs   21 annotated
    formal/hostmods/struct.mojo                8 defs    6 annotated
    formal/hostmods/argparse.mojo            107 defs    2 annotated   <- until 2026-09-30

`argparse.mojo` was the outlier by an order of magnitude: 0 of 107 before this
branch, which is why it and only it was refused for a comparison of two words of
unknown kind. The unannotated remainder elsewhere is deliberate and small —
`re.mojo`'s `IGNORECASE()`/`STATUS_OK()`/… constants and the four public entry
points that take a caller-supplied `out`/`status` parameter (`group_text`,
`findall`, `sub`, `split`), `os/path`'s three tuple-returners and
`_next_component` (`os/__init__.mojo`'s bullet on annotations says why a tuple
carries none), `struct`'s `pack`/`unpack_from`, `time`'s `rne_scaled`, and
hashlib's five wide-output helpers.

## Why it matters beyond a table

Two numbers about this backend are quoted in more places than any other, and both
of them are denominators over files this table describes. `argparse.mojo` not
building did not make 37 files fail for a reason of their own: it made them
unbuildable, and a sweep that cannot classify a file cannot say anything about
it. `hashlib.mojo` not building on x86-64 has the same shape one architecture
over. The per-module build is the cheapest possible early warning for both, and
as of this commit only `argparse.mojo` has one
(`test_formal_argparse.py::test_the_module_builds_on_its_own`).