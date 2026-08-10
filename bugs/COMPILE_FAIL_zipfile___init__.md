# COMPILE_FAIL: Lib/zipfile/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-09)

Re-ran fresh; error set has SHIFTED since the previous write-up (some
line numbers moved, the previous vague "line-number misattribution,
not root-caused further" writeup is replaced below with concrete root
causes for each). Nothing fixed this session — all four are either a
new instance of an already-tracked structural gap, or open up a
genuinely new one; none looked safely narrow enough to touch given
this session's time budget and this codebase's documented history of
narrow-looking fixes to shared type-inference machinery causing broad
silent regressions.

```
error: assignment to '_Extra *' from 'int64_t' makes pointer from
       integer without a cast          (line 228)
error: non-trivial conversion in 'integer_cst'   (x2, near line 567,
       actually ZipInfo.FileHeader ~line 547-548)
error: mismatching comparison operand types       (near line 625,
       actually ZipInfo.FileHeader ~line 542)
error: passing argument 3 of 'ZipFile_mojo_open' makes integer from
       pointer without a cast           (line 1690)
error: passing argument 3 of 'PyZipFile_mojo_open' makes integer from
       pointer without a cast           (line 1699)
```

1. **Line 228, `_Extra.strip`** (a `@classmethod`, NOT itself a
   generator — it calls `cls.split(data)`, which IS a `@classmethod`
   generator, from inside a generator-expression consumed by
   `b''.join(...)`). Traced via the generated `.ci`:
   `_Extra_strip(int64_t cls, int64_t data, int64_t xids)`'s body does
   `_t6 = cls;` into a temp DECLARED `_Extra *`, then
   `_mojogen__Extra_split_start(_t5, data)` (the generator's start
   function) — i.e. codegen is trying to pass `cls` as a real `_Extra
   *` receiver pointer to the generator constructor, but `cls`'s own
   parameter is declared plain `int64_t` in `_Extra_strip`'s own
   signature. This is a NEW manifestation of the classmethod-generator
   family already tracked in `bugs/hard/
   CODEGEN_generator_classmethod_first_param_must_be_self.md` (marked
   FIXED for the "a generator METHOD's own first param is cls" case),
   but this is the mirror shape: a NON-generator method CALLING another
   class's classmethod generator via `cls.method(...)`. `split`'s own
   `cls` (unused in `split`'s body — it calls `_Extra.read_one(...)` by
   bare class name, not `cls.read_one`) gets compiled as an opaque,
   never-read `int64_t cls` placeholder per that fix's documented
   approach — but the CALL SITE in `strip` doesn't know that and tries
   to pass a real pointer value anyway. Fixing this correctly means
   teaching the `cls.method(...)` call-site lowering (wherever it
   decides how to pass the receiver arg to a classmethod-generator's
   start function) to agree with how that generator's OWN parameter got
   compiled — genuinely touches the same fragile classmethod-generator
   machinery that took three separate incidents to get right the first
   time (per that doc's own history). Classified structural; not
   attempted.

2. **`ZipInfo.FileHeader`, lines ~530-548** (GCC's own `#line`
   attribution points at 567/625 — blank/docstring lines past the
   function, the same "-fgimple errors point at the last-seen `#line`
   directive, not the real one" pattern noted in the previous version
   of this doc; the REAL culprit is inside `FileHeader`, confirmed via
   GCC's own printed statement text, e.g. `file_size = 4294967295;`).
   `compress_size`/`file_size` are LOCAL variables:
   `if ...: CRC = compress_size = file_size = 0` (a chained multi-
   assign, RHS `0`) `else: compress_size = self.compress_size;
   file_size = self.file_size` (a plain single assign from a STRUCT
   FIELD). Whichever assignment `_infer_local_var_types`'s whole-body
   pre-pass used to lock these locals' declared C type picked plain
   `int` (32-bit) — almost certainly inherited from
   `self.compress_size`/`self.file_size`'s own STRUCT FIELD ctype,
   itself narrowed to `int` because `ZipInfo.__init__` only ever
   initializes them with the small literal `0` (line 480-481). Later in
   the SAME function, `file_size = 0xffffffff; compress_size =
   0xffffffff` (~547-548, real ZIP64 sentinel values, both
   4294967295 — exceeds `INT32_MAX`) assigns a literal that doesn't fit
   the locked-in 32-bit `int`, which `-fgimple` rejects outright
   ("non-trivial conversion in 'integer_cst'") rather than silently
   truncating. The "mismatching comparison operand types" error a few
   lines earlier (`zip64 = file_size > ZIP64_LIMIT or ...`, ZIP64_LIMIT
   = `(1 << 31) - 1`, an `int64_t`-range constant) is the SAME root
   cause: comparing the (wrongly 32-bit) `file_size` against a value
   the codegen infers as 64-bit. This is a struct-field-type-
   propagation gap (a plain-Python `int` field whose only *literal*
   initializer happens to fit 32 bits gets under-widened, then a later
   *local* reassignment with a value that needs the full 64 bits
   breaks) — recognized as matching this session's "struct-field
   type-propagation gap on assignment" pattern, but the actual fix
   surface (wherever a struct field's ctype gets decided from its
   `__init__` literal initializers) is shared machinery touched by
   several other already-fragile field-typing bugs in this session's
   history; not attempted given the same caution.

3. **Lines 1690/1699, `ZipFile.read`/`PyZipFile` opening a member with
   a password**: `def read(self, name, pwd=None): with self.open(name,
   "r", pwd) as fp: ...` — `pwd` is an unannotated `bytes | None = None`
   parameter forwarded positionally into `self.open(...)`'s own `pwd`
   parameter (also `bytes | None = None`). The call site's `pwd` value
   resolves to `int64_t` (the standard "unannotated param defaulting
   from a bare `None` literal infers int64_t" gap, same family as
   `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
   int64.md`), while the callee's OWN declared parameter type for
   `pwd` apparently resolved differently (a pointer type, from some
   OTHER call site elsewhere in the file that passes a real bytes
   value) — a caller/callee signature disagreement, "makes integer
   from pointer without a cast". Same structural class as `bugs/hard/
   CODEGEN_unannotated_init_param_field_type_defaults_int64.md`; not
   attempted here for the same reason as issue 2 above (shared
   call-argument type-inference machinery).

None fixed here. All four are either instances of already-tracked
structural gaps or open a closely related new one in the same
machinery — kept open rather than force a narrow-looking fix into
code this session's own history shows is easy to silently break
broadly.

Exit code: 1
