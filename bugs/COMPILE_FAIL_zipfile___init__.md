# COMPILE_FAIL: Lib/zipfile/__init__.py

## Status (updated 2026-08-25, wtOpencode_zipfile / fix/opencode-zipfile -- TWO of the four groups FIXED, error set shifted again)

Re-ran fresh. The error set has SHIFTED again since the 2026-08-24
re-check: issue group (1)'s call-site half was fixed on another branch
(2c9fe02, "module-qualify + cross-module hint compiled generator
symbols") between sessions, so compilation now gets further and dies
EARLIER, on a new first-order blocker inside `_Extra.split` itself:

```
Error building: cannot compile module: function(s) split (generator ...)
 Unsupported shape(s): split: a call to unresolved callee
 'memoryview(...)' is not supported in a compiled generator/coroutine
 body (...)
```

**NEW FIRST BLOCKER — memoryview in a compiled generator body.**
`_Extra.split` (a `@classmethod` generator) does `rest = memoryview(data)`
then `while rest:` + slices. `memoryview` has NO implementation anywhere
in this codegen (zero occurrences outside bugs/ docs): strings/bytes are
NUL-terminated `char *`, and there is no {ptr,len} buffer-view value.
Honest support means a real view type (slicing producing sub-views,
length-based truthiness, `.nbytes`) across BOTH the ordinary GIMPLE path
and the C++ coroutine-body path — zipfile also uses `memoryview` in
`_ZipWriteFile.write` (~line 1334, non-generator). Note the NUL-
termination problem too: ZIP extra fields legitimately contain 0x00
bytes, so even a char*-identity lowering would be semantically wrong.
Feature-sized; not attempted.

To expose the blockers BEHIND it, diagnosed against a scratch copy
(`/tmp/zipdiag/zf.py`, `split`'s body de-memoryview'd — diagnostic only,
no runtime fidelity claimed for that copy). With memoryview out of the
way the remaining error set is exactly four gcc diagnostics, and TWO of
the doc's four groups are now genuinely FIXED (all four quality gates
green after each change; test_gimple 253/253, test_module_cache 76/76,
self-host clean, stdlib dylib 0 skips):

1. **FIXED (commit 6fc759a) — group (2), FileHeader int32 under-widening.**
   Root cause was NOT struct-field narrowing as theorized below (the
   `self.compress_size = 0` fields are typed int64_t just fine). The real
   bug: `_gen_stmt_MultiAssignStmt` declared a first-time chained-assign
   target from the RAW lowered RHS type — literal `0` lowers to C 'int' —
   ignoring the function-wide `_inferred_var_types` hint that the single-
   target path (`_assign_target`) has consulted since
   CODEGEN_multi_assign_local_var_type_not_inferred.md. That hint DOES
   see `file_size = 0xffffffff` later in the body (int64_t), so honoring
   it declares the locals int64_t and both "non-trivial conversion in
   'integer_cst'" errors and the comparison-operand error vanish.
   Verified end-to-end: minimal repro (chained zero-init + 0xffffffff
   reassign + ZIP64_LIMIT comparison) compiles AND returns correct
   values (zip64 sentinel path fires: 2x4294967295).

2. **FIXED (commit 4d3626d) — group (1) RESIDUE, `_Extra.strip`'s
   `cls.split(data)` call.** After 2c9fe02 one -Wint-conversion remained:
   `_lower_method_call`'s generator-method branch passed the
   POST-resolution receiver pair to `<base>_start`; the classmethod-
   receiver block had by then retagged `cls`'s int64_t pair to
   `'_Extra *'`, and coercing that into the start function's slot 0
   (the opaque never-read int64_t cls placeholder per
   gimple_cpp_async.py's param_ctypes) went through
   `_ensure_local('_Extra *', 'cls')` → `_Extra * _t6 = cls;`. Now, when
   slot 0 of the registered start signature is 'int64_t' (exactly the
   classmethod-placeholder shape) and the receiver lowered to a scalar,
   the raw pre-resolution pair is passed straight through. Verified
   end-to-end with a minimal classmethod-generator + genexp-consumed-by-
   join repro: compiles AND produces correct output.

3. **FIXED (commit 4094f7a) — NEW residual found this session.**
   `ZipFile._sanitize_windows_name`: "request for member
   '_windows_illegal_name_trans_table' in something not a structure or
   union". The method-scalar-observation pass mapped call args onto
   parameter names excluding only 'self', so the instance-called
   classmethod `self._sanitize_windows_name(arcname, os.path.sep)`
   observed arcname's 'char *' evidence onto `cls` (and shifted every
   later observation up a slot). cls then being 'char *' made the body's
   `cls._windows_illegal_name_trans_table = table` write emit a raw
   `cls->_attr` field store on a non-struct. Classmethods now exclude
   their implicit `cls` receiver from arg→param mapping. Both x2 error
   groups gone.

REMAINING after these fixes (scratch copy; real file additionally blocked
by memoryview above):

- **pwd caller/callee disagreement x2 (read/testzip → mojo_open)** —
  unchanged in substance: callee `open(..., pwd=None)`'s slot resolved
  int64_t while `read`'s forwarded `pwd` is inferred 'char *'. Confirmed
  this is exactly the unannotated-None-default-param family (
  bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md);
  explicitly out of scope this session per campaign rules. Still open.
- **`_sanitize_windows_name` "non-trivial conversion in 'mem_ref'" x2**
  — different root cause than the (now-fixed) member-store error: the
  source REBINDS `arcname` to a generator-expression OBJECT
  (`arcname = (x.rstrip(' .') for x in arcname.split(pathsep))`) and the
  next statement ITERATES that local (`pathsep.join(x for x in arcname
  if x)`). This scalar model can't hold a genexp object in a local, so
  `arcname` stays char* and the second loop lowered as CHAR iteration
  (`x = *_t36` deref) colliding with the char*-typed loop var declared by
  the first loop. Local-held generator/genexp consumed as an iterable is
  the same feature-sized family recorded on fsutil.py's six-generator
  refusal list; not attempted.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. All four residual issues (classmethod-generator receiver-passing mismatch in `_Extra.strip`; `int`/`int64_t` struct-field width under-inference in `FileHeader`; the `pwd=None` caller/callee signature disagreement) are unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies -- none of this file's own blockers touch string methods or stdin/stdout/stderr-named fields). Still structural / shared fragile type-inference machinery; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/zipfile/__init__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-23, wt09 fix/stdlib-mods `945af88` — unchanged in substance)

Re-ran the repro fresh. Same four issue groups as the 2026-08-09
analysis below, none fixed this pass either:

```
error: assignment to '_Extra *' from 'int64_t' ... makes pointer from
       integer without a cast          (_Extra.strip, line 228)
error: non-trivial conversion in 'integer_cst'   (x2, FileHeader ~547-548)
error: passing argument 2/3 of 'ZipFile_mojo_open'/'PyZipFile_mojo_open'
       makes integer from pointer without a cast  (~1666/1690/1699, pwd)
```

Assessment reconfirmed for each: (1) `_Extra.strip`'s `cls.split(data)`
call site vs. the classmethod-generator machinery that per the write-up
below took three incidents to stabilize — deliberately untouched;
(2) FileHeader's compress_size/file_size locals under-widened from the
`int`-typed struct fields (themselves narrowed from literal-`0` init) —
a shared field-typing-machinery change, not narrow; (3) the `pwd=None`
caller/callee signature disagreement — same unannotated-param family.
Still open; no code changes made this pass.

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
