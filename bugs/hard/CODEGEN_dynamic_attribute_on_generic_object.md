# HARD BUG: setting/getting an arbitrary attribute on a generically-typed object

## Status

**Step 0 implemented and verified 2026-08-06** (see "Step 0" below for
what landed). **Steps 1-4 implemented and verified 2026-08-07** (see
"Steps 1-4 implementation notes" below) — real per-object dynamic-
attribute storage, a genuine catchable AttributeError on a miss, and
Sub-case C (fixed-layout runtime structs like `MojoBoundMethod`) all now
work end-to-end, confirmed via full compile+run repros (not just "stops
erroring at compile time"). One residual gap found during real-world
verification and deliberately NOT fixed here — see "Residual gap: caught
exception objects" below.

### Steps 1-4 implementation notes (2026-08-07)

Implemented essentially as planned, in `runtime/mojo_runtime.c`/`.h` and
`gimple_codegen.py`:

- **Step 1 (runtime storage)**: `_mojo_dynattr_objects` (a lazily-
  allocated `MojoDict *` keyed by the object pointer's hex text, reusing
  `MojoDict`'s existing string-keyed hash table rather than a second
  pointer-keyed one) + `_mojo_dynattr_key`, exactly as the plan's own
  pseudocode. `mojo_setattr` now actually stores; `mojo_obj_getattr` now
  actually reads.
- **Step 2 (real AttributeError)**: `mojo_raise_attribute_error(char *
  attr)`, mirroring the EXACT runtime call sequence compiled `raise
  AttributeError(...)` itself lowers to (`_gen_stmt_RaiseStmt`:
  `mojo_exc_type_set` + `mojo_exc_msg_set` + `mojo_exc_obj_set` +
  `mojo_raise`) — including `mojo_exc_type_set`, which the plan's own
  illustrative pseudocode omitted. Without it, only the lenient
  untagged-exception fallback would match (correct for a single-handler
  `except AttributeError:` by coincidence, but not a real match, and
  wrong for a multi-handler try where `AttributeError` isn't the first
  clause). The tag is `GimpleGen._exc_type_id('AttributeError')` —
  `(zlib.crc32(b"AttributeError") & 0x7fffffff) or 1` = `1471495998`,
  computed once via Python and hardcoded as `_MOJO_EXC_TAG_ATTRIBUTEERROR`
  in the C runtime (this is a pure, deterministic function of the class
  name string per `_exc_type_id`'s own docstring, so a value computed
  once in Python and never revisited is safe as long as that function's
  algorithm doesn't change — flagged in the C comment so it stays
  discoverable if it ever does).
- **Step 3 (wire the dispatch)**: needed zero codegen changes, confirmed
  — `_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`'s existing
  fallthrough already called `mojo_obj_getattr`/`mojo_setattr` (Steps
  1-2 alone make Sub-cases A/B work end to end).
- **Step 4 (Sub-case C, fixed-layout runtime structs)**: new
  `_FIXED_RUNTIME_STRUCT_NAMES = frozenset({'MojoBoundMethod',
  'MojoGenerator', 'MojoAsync'})`, checked at THREE write-side call sites
  (plain `AssignStmt` MemberExpr target, `AugAssignStmt` MemberExpr
  target, AND `MultiAssignStmt`/chained-assignment MemberExpr targets —
  see "A fourth call site found during verification" below for why the
  third one was necessary) and one read-side site (`_lower_MemberExpr`'s
  final "unknown struct field" fallback, which previously blindly emitted
  a raw `->member` access GCC rejects for a struct with no such field).

### A fourth call site found during verification, not in the original plan

The doc's own minimal repro (`slotnames = cls.__slot_names__ = []`) is a
**chained assignment** — Python's `a = b = c` shape, which this codegen
lowers via a wholly separate function, `_gen_stmt_MultiAssignStmt`, not
the single-target `_gen_stmt_AssignStmt` the plan's "gimple_codegen.py:
16498-16502" line reference pointed at. Running the repro through
`mojo.py build` immediately surfaced this: `MultiAssignStmt`'s own
`MemberExpr`-target handling had **neither** the opaque-object dispatch
(Sub-case A/B) **nor** the fixed-runtime-struct dispatch (Sub-case C) —
it unconditionally emitted a raw `ov->field = v`, for every target type.
Fixed by adding both checks there too, mirroring the single-target
branch exactly (including the `continue` to skip the shared fallback
write once handled). Worth flagging for anyone touching this dispatch
class of check in the future: **there are (at least) three distinct
write-side lowering functions for a `MemberExpr` target** (`AssignStmt`,
`AugAssignStmt`, `MultiAssignStmt`), and a fix scoped to just one or two
of them will compile clean for simple repros while silently missing the
chained-assignment shape specifically — which is exactly the shape this
bug's own canonical minimal repro uses.

### A fifth gap found during verification: `.__name__`'s own special case

`_lower_MemberExpr` has an EARLIER, unconditional special case for
`node.member == '__name__'` (the `type(x).__name__` / AST-walker
dispatch chokepoint, pre-existing and unrelated to this bug) that
returns a hardcoded `"<type>"` placeholder string for ANY receiver type
not in `self.struct_field_types` — including `MojoBoundMethod`,
intercepting `f.__name__` reads BEFORE they ever reach Step 4's new
fixed-runtime-struct branch further down the same function. Confirmed
via the Sub-case C repro below: it compiled and ran fine but printed
`<type>` instead of the dynamically-set name. Fixed narrowly: this
special case now routes through the same `_mojo_dispatch_getattr` (cast
back to `char *`, since `__name__` is always conceptually a string) when
the receiver is opaque OR a fixed-runtime-struct name — every OTHER
"not in struct_field_types" case (the special case's original, documented
purpose) keeps the original `"<type>"` stub unchanged.

### Residual gap: caught exception objects (found, NOT fixed)

`Lib/pathlib/_os.py`'s `except OSError as err: ... err.filename = ...`
(one of the doc's own confirmed real-world instances) is **still
broken** after Steps 1-4 — a real, distinct gap, not a verification
oversight. Traced via direct `.ci` inspection: the caught exception
object (`err`) is lowered as a bare `mojo_exc_obj_get()` result cast
directly to `char *` (`_t134 = (char *) _t133;`) — this runtime models
an exception's "object" payload as a plain message string, not a real
struct/object with its own identity. `err.filename = ...` therefore
tries to write through a `char *`-typed receiver, which is neither
Sub-case A/B (`ot` is `char *`, not `int`/`int64_t`/`void *`) nor
Sub-case C (`char *` isn't a `_FIXED_RUNTIME_STRUCT_NAMES` member) — it's
a genuinely different, third receiver-type shape this doc's Steps 1-4
scope never covered. Deliberately not fixed here: broadening the opaque-
dispatch condition to also match bare `char *` receivers would catch
this case, but `char *` is used PERVASIVELY throughout this codegen for
ordinary, unrelated string values — adding it to the same dispatch
condition risks matching unintended cases far outside this bug's scope
(this project's documented history of exactly this kind of narrowly-
scoped-looking change to shared dispatch/type machinery causing
hard-to-predict regressions — see `bugs/COMPILE_FAIL_collections___init__.md`
— made a same-session broadening attempt feel unjustifiably risky without
a much more careful, dedicated look at every other `ot in (...)` call
site sharing that exact tuple literal). Confirmed via direct `.ci`
inspection only (0 "structure or union" errors is the OTHER 4 confirmed-
instance files' verification method below) — `pathlib/_os.py` itself was
NOT re-verified against the full gate-style error-count comparison; it
simply still shows the exact same 2 "request for member 'filename'/
'filename2' in something not a structure or union" errors as before this
session's changes, unchanged.

### Verification against real-world files (2026-08-07)

Direct `gimple_codegen.compile_to_gimple(..., do_imports=True)` +
`gcc -fsyntax-only` (0 "request for member ... in something not a
structure or union" errors is the pass criterion — a different,
unrelated error is an acceptable/expected outcome per this session's
established norm, since these are real, large, third-party files with
many independent gaps):

| file | doc's confirmed symptom | after Steps 1-4 |
|---|---|---|
| `Tools/c-analyzer/c_common/clsutil.py` | `cls.__slot_names__` (A/B) + `__del__._slotted` (C) | 0 "structure or union" errors (0 gcc errors at all); LINK fails on an unrelated, separate missing-symbol bug (`_Slot__ensure___del___lambda_1`, `_classonly_getter`) |
| `Lib/collections/__init__.py` | `self.__hardroot = _Link()` on opaque `self` | 0 "structure or union" errors; 6 unrelated errors (redefinition, pointer-type mismatches) |
| `Lib/ctypes/__init__.py` | `c_ubyte.__ctype_le__ = c_ubyte.__ctype_be__ = c_ubyte` on a class object | 0 "structure or union" errors; 2 unrelated "too many arguments" errors |
| `Lib/string/__init__.py` | `cls.pattern = re.compile(...)` in `__init_subclass__` | 0 "structure or union" errors; 2 unrelated "invalid conversion in gimple call" errors |
| `Tools/scripts/var_access_benchmark.py` | `inner.__name__ = ...` write + `f.__name__` read on `MojoBoundMethod` (Sub-case C) | 0 "structure or union"/"has no member named" errors; 2 unrelated "undeclared" errors |
| `Lib/pathlib/_os.py` | `err.filename = ...` on a caught exception object | **UNCHANGED** — see "Residual gap" above, a genuinely different receiver-type shape |

Two hand-written, self-contained repros were compiled AND RUN (not just
syntax-checked) end to end, confirming actual runtime behavior, not just
absence of a compile error — both also landed as permanent regression
tests, `test_gimple_runner.py`'s `gimple_dynamic_attribute_real_storage_
and_attributeerror` and `gimple_dynamic_attribute_fixed_runtime_struct_
bound_method`:

1. The doc's own minimal repro pattern (`try: x = cls.__slot_names__
   except AttributeError: x = cls.__slot_names__ = []`), extended to call
   twice with the SAME object: first call takes the `except` branch
   (`mojo_raise_attribute_error` genuinely fires and is genuinely caught)
   and initializes; second call takes the fast path and sees the value
   the FIRST call actually stored (`mojo_setattr`'s storage is real and
   persists per-object, not merely "no longer crashes"). Output matched
   exactly: `miss, initializing` / `after first call: 1` / `fast path,
   got: 1` / `after second call: 2`.
2. Sub-case C: a capturing closure (`MojoBoundMethod *`) gets `.__name__`
   set then read back, plus called — confirms both the write-side Step 4
   fix AND the separate `__name__`-special-case fix (see above) together.
   Output matched exactly: `read_nonlocal` / `11`.

### Quality gate (2026-08-07, Steps 1-4)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed (including the
   link-mode tiny-client-object size-budget check Step 0's own regression
   was found through).
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).
6. `python3 test_gimple_runner.py` — 18 passed, 0 failed (16 pre-existing
   + the 2 new regression tests above). Not one of the mandatory 5, but
   the only suite in this repo that actually EXECUTES compiled output and
   checks real stdout, which is what this fix's own correctness hinges
   on (compiling clean is necessary but not sufficient — Step 0's own
   `.__dict__`/`vars()` fix already documented this same distinction).

### Step 0 implementation notes

`obj.__dict__` (a `MemberExpr` with `.member == '__dict__'`, gated on
`struct_name in self.struct_field_types` — i.e. only for a struct with
statically-known fields, exactly Step 0's scope) and `vars(obj)` (the
1-arg builtin call, same gating) both now lower to a call to a new
`_mojo_dispatch_asdict(void *)` runtime-tag dispatcher, mirroring the
existing `_mojo_dispatch_fields`/`_mojo_dispatch_getattr` machinery
exactly. Each reflect-eligible struct gets a companion
`_mojo_asdict_<StructName>(StructName *)` that builds a real `MojoDict *`
of name→value pairs from the struct's own known fields (reusing the
per-struct field loop that already builds `_mojo_getattr_<sn>`/
`_mojo_setattr_<sn>`/`_mojo_fieldnames_<sn>`, not a second, separately-
maintained field enumeration), boxing every value via `mojo_dict_set_int`
— the same generic boxed-int64_t convention every other heterogeneous
`MojoDict *`/`MojoList *` this codegen builds already uses (see
`_mojo_generic_elem_repr`'s existing magnitude/registered-list-or-dict/
type-tag heuristic, which is what actually makes
`print(obj.__dict__)`/`pprint.pprint(retval.__dict__)` — the doc's own
real-world confirmed use case — print correctly: `{'name': 'hello',
'value': 42}`, not raw integers). Verified: a repro with `c.__dict__`
and `vars(c)` both compiled and ran, printing the correct dict repr for
a struct with a `char *` field and an `int64_t` field.

**Known limitation, by design, not a regression**: reading an individual
key back out of the resulting dict with a Python-level-typed expectation
(`obj.__dict__["name"]` used as a string, printed directly rather than
through the dict's own generic repr) prints the raw boxed int64_t
(pointer bits interpreted as a number), because a single `MojoDict *`
in this codegen has one static declared value type and there's no
runtime type tag stored per-key. This is inherent to how EVERY
heterogeneous/generic `MojoDict *`/`MojoList *` this codegen already
builds works (reflection tables, `dataclasses.fields()`'s field-name
list, etc.) — not something Step 0 introduces or could fix without a
genuinely new per-value type-tagging scheme, well outside "Step 0,
easiest, do first" scope. The confirmed real-world call sites
(`Tools/build/umarshal.py`/`deepfreeze.py`'s `retval.__dict__`) only
ever pass the whole dict to `pprint.pprint`, never re-subscript it with
a typed expectation, so this limitation doesn't block them.

**Gating to avoid a real regression found during verification**: an
early version emitted `_mojo_dispatch_asdict` and its forward
declaration unconditionally (matching its 4 siblings —
`_mojo_dispatch_getattr`/`setattr`/`fields`/`is_dataclass`, which
genuinely must stay unconditional since any module in a whole-program
closure might call bare `getattr()`/`dataclasses.fields()` on another
module's struct with no local trace of the call). Doing the same for
`_mojo_dispatch_asdict` regressed `test_module_cache.py`'s "reflect:
client object is tiny — bodies live in the dylib" size-budget check (a
link-mode client whose whole architectural point is staying tiny). Fixed
by gating both the per-struct `_mojo_asdict_<sn>` bodies and the
`_mojo_dispatch_asdict` dispatcher (definition AND forward declaration)
on a new shared flag, `GimpleGen._asdict_dispatch_needed` (a `set`, following
this codegen's established "shared mutable container across nested
temp_gens" pattern — see `_compiled_modules`/`_emitted_structs` etc.),
set by the two new call sites during lowering and checked at emission
time (which always happens after all lowering, so the flag is fully
populated by then regardless of import nesting). Verified: with no
`.__dict__`/`vars()` call anywhere in a compile, the dispatcher and its
per-struct bodies are entirely absent from the output, and
`test_module_cache.py`'s tiny-client-object check passes again.

Full 5-part quality gate after Step 0: `test_gimple.py` (247/247),
`test_module_cache.py` (76/76, including the size-budget check),
`make check-selfhost` (pass), from-scratch stdlib dylib rebuild (0
`skip <module>:` lines), `compile_stdlib.py -j8` (664/664, 0
unexpected — see this doc's own commit for the exact run).

## Symptom

`request for member 'X' in something not a structure or union` (GCC
`-fgimple` error), or (a second, distinct shape — see "Sub-case C" below)
`'MojoBoundMethod' has no member named 'X'`.

This codegen models attribute access (`obj.field`) as a real C struct-field
read/write, which requires knowing `obj`'s concrete struct layout ahead of
time. When `obj`'s static type can't be resolved to a known struct — most
commonly a bare, unannotated parameter whose real runtime type is something
generic like a class object (`type`) or a closure/function value — it falls
back to a generic `int64_t`/opaque representation with **no** attribute
storage at all.

## Minimal repro

```python
# dynamic_attr_repro.mojo
class Slot:
    def __set_name__(self, cls, name):
        try:
            slotnames = cls.__slot_names__
        except AttributeError:
            slotnames = cls.__slot_names__ = []
        slotnames.append(name)
```

## Real-world files exposing this (all confirmed live, 2026-08-06)

- `Tools/c-analyzer/c_common/clsutil.py` — `Slot.__set_name__`'s
  `cls.__slot_names__` (opaque `cls` param, Sub-case A/B below) AND
  `Slot._ensure___del__`'s `__del__._slotted = True` (Sub-case C below,
  `'MojoBoundMethod' has no member named '_slotted'`).
- `Lib/collections/__init__.py`'s `OrderedDict.__new__`: `self =
  dict.__new__(cls)` (opaque `self`) then `self.__hardroot = _Link()`.
- `Lib/ctypes/__init__.py`: `c_ubyte.__ctype_le__ = c_ubyte.__ctype_be__ =
  c_ubyte` at module top level, on a class object.
- `Lib/string/__init__.py`'s `Template.__init_subclass__`: `pat =
  cls.pattern = re.compile(...)`. (Also breaks `Lib/importlib/__init__.py`,
  which imports `string` transitively.)

### More real-world instances confirmed 2026-08-06 (Sub-case C, same as `__del__._slotted`)

- `Tools/scripts/var_access_benchmark.py`: `inner.__name__ =
  'read_nonlocal'` (setting `__name__` on a closure/`BoundMethod` value —
  a WRITE, same "fixed-layout runtime struct, unknown field" shape as the
  doc's own `__del__._slotted = True` example) and separately reads
  `f.__name__` on a `MojoBoundMethod` elsewhere in the same file
  ("'MojoBoundMethod' has no member named '__name__'").
- `Lib/importlib/_bootstrap.py`'s `PathFinder._resolve_filename`:
  `sep = cls._SEP` / `sep = cls._SEP = '\\' if ... else '/'` inside a
  classmethod — `cls` is the opaque implicit class-reference parameter,
  `_SEP` a lazily-stashed class attribute via the `hasattr`/
  `AttributeError`-catch idiom — "request for member '_SEP' in
  something not a structure or union".
- `Lib/importlib/__init__.py`'s `reload(module)`: `module.__spec__` read
  AND written (`module.__spec__ = _bootstrap._find_spec(...)`) on the
  bare, unannotated `module` parameter (any module object at the Python
  level) — "request for member '__spec__' in something not a structure
  or union".
- `Doc/tools/extensions/glossary_search.py` (Sphinx extension):
  `app.env.glossary_terms = {}` / `hasattr(app.env, 'glossary_terms')` —
  `app.env` is a `sphinx.environment.BuildEnvironment` instance from the
  third-party `sphinx` package (unresolvable to this compiler, same as
  `cls`/`self` being opaque in the doc's own Sub-case A/B examples above),
  and the WHOLE POINT of this code is Sphinx's own documented extension
  idiom of stashing arbitrary custom state on `app.env` via `hasattr`/
  dynamic-attribute assignment. "request for member 'glossary_terms' in
  something not a structure or union".
- `Lib/pathlib/_os.py` (confirmed 2026-08-06, via
  `bugs/COMPILE_FAIL_pathlib___init__.md`): `except OSError as err: ...
  err.filename = source_f.name; err.filename2 = target_f.name` —
  writing NEW attributes onto a caught EXCEPTION object. Same opaque-
  object shape as sub-cases A/B (the exception's real runtime type
  isn't one this compiler models with a known struct layout).
  "request for member 'filename'/'filename2' in something not a
  structure or union".
- `Tools/build/umarshal.py` / `Tools/build/deepfreeze.py`: `retval.__dict__`
  / `pprint.pprint(retval.__dict__)` where `retval`/the target is a KNOWN
  user struct (`Code`) — "'Code' has no member named '__dict__'". This is
  actually a THIRD variant, distinct from Sub-cases A-C: unlike `_slotted`
  (a genuinely NEW, never-declared field) or `.pattern`/`.__slot_names__`
  (opaque `cls`), `__dict__` here needs to return a real dict VIEW of the
  struct's OWN ALREADY-KNOWN fields (matching Python's real `obj.__dict__`
  semantics) — the fix doesn't need generic dynamic storage for this one
  specifically, it could reuse the EXISTING `_mojo_dispatch_fields`/
  `dataclasses.fields()` reflection machinery (already emits a
  `_mojo_fieldnames_<struct>()` per known struct) extended to build a real
  `MojoDict *` of name->value pairs instead of just a name list — worth
  implementing as an easy, narrow special case for `__dict__`/`vars()` on
  a struct with ALL-known fields, ahead of (or independent from) the full
  generic-dynamic-storage plan below, which remains necessary for the
  genuinely-new-attribute cases (Sub-cases A/B/C).

## What's ALREADY there (the key finding that shrinks this task)

This codegen already has a generic runtime-dispatch choke point for
exactly this situation, emitted once per module
(gimple_codegen.py:30332-30356):

```c
static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {
  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
  if (_tag == <known-struct-1-id>) return _mojo_getattr_<struct1>((...)obj, attr);
  ... /* one line per known struct */
  return mojo_obj_getattr(obj, attr);   /* <-- current dead end */
}
static void _mojo_dispatch_setattr (void *obj, char *attr, int64_t val) {
  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
  if (_tag == <known-struct-1-id>) { _mojo_setattr_<struct1>(...); return; }
  ...
  mojo_setattr(obj, attr, val);          /* <-- current dead end */
}
```

And **every** codegen call site that lowers `obj.attr` (read or write) on
an opaquely/generically-typed value already routes through these two
functions rather than emitting a direct field access — confirmed by
reading the actual call sites, not assumed:

- Read: gimple_codegen.py:8470 (`ot in ('int','int64_t','void *') or ot in
  ('MojoList *', 'MojoDict *', ...)` branch of `_lower_MemberExpr`) and
  :13251/:13270 (a second, similarly-gated read path).
- Write: gimple_codegen.py:16496 (`ot in ('int', 'int64_t', 'void *')`
  branch of the assignment lowering) and :16737 (an augmented-assignment
  analogue).

So sub-cases A and B below (opaque `cls`/`self`/class-object values) need
**zero** new call sites in the lowering code — they already call into
`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`. The only missing piece
is what those two functions do when no known-struct tag matches: today,
`mojo_obj_getattr` (runtime/mojo_runtime.c:2424) unconditionally
`fprintf`s a warning and returns 0, and `mojo_setattr`
(runtime/mojo_runtime.c:3335) is a silent no-op. Neither has ever
implemented real storage — this was always a deliberate stub, not a
regression.

## Sub-case C (`MojoBoundMethod` etc.): a separate, second gap

`__del__._slotted = True` does NOT go through the opaque-fallback path
above — `__del__` is a locally-defined closure, whose static type this
codegen already resolves to a *known* runtime struct (`MojoBoundMethod`).
The assignment lowering's `else` branch (gimple_codegen.py:16498-16502)
handles "known concrete struct type" by looking up the field with a
silent default:

```python
field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
self._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{_safe_field(node.target.member)}")
```

For a user-defined Mojo class, a not-yet-seen field name here is fine —
`struct_field_types[struct_name]` is itself mutable and gets new fields
appended elsewhere as they're discovered (see `_collect_self_assigns`/
`_scan_body_for_local_field_access`), and the struct's actual C layout
grows to match (`target_def.fields.append(...)`, gimple_codegen.py:26503).
But `MojoBoundMethod` (and similarly `MojoGenerator`, `MojoAsync`, any
other **runtime-owned, fixed-layout C struct this codegen itself
defines**, as opposed to a user's own Mojo class) has a hardcoded C struct
definition in the runtime headers with no such extensibility — the
`.get(..., vtype)` default silently assumes the field exists and emits a
direct `->_slotted` access GCC then rejects because the struct genuinely
has no such member.

## Implementation plan

### Step 0 (independent, easiest, do first) — `__dict__`/`vars()` on a struct with all-known fields

Doesn't need Steps 1-4's dynamic storage at all. `_mojo_dispatch_fields`/
`_mojo_fieldnames_<struct>()` (gimple_codegen.py, emitted per reflect-
eligible struct — see the `reflect_structs`/`tag_cases_fields` preamble
emission near `_mojo_dispatch_getattr`) already returns a `MojoList *` of
FIELD NAMES for `dataclasses.fields()`. Add a companion `_mojo_asdict_
<struct>()` (or extend the existing one) that returns a real `MojoDict *`
of name->value pairs instead, by reading each known field off the
instance the same way `_mojo_getattr_<struct>` already does per-field —
then route `obj.__dict__` (a MemberExpr with `.member == '__dict__'` on a
value whose struct is known and reflect-eligible) and `vars(obj)` (the
1-arg form) to call it. Confirmed real instances: Tools/build/umarshal.py
Tools/build/deepfreeze.py's `retval.__dict__` where `retval: Code` (a
known struct with statically-enumerable fields) — "'Code' has no member
named '__dict__'".

### Step 1 — real per-object dynamic-attribute storage (runtime)

Add to `runtime/mojo_runtime.c`, next to `mojo_obj_getattr`/`mojo_setattr`:

```c
/* obj-pointer -> its dynamic-attribute MojoDict, keyed by the pointer's
 * hex text (reuses MojoDict's existing string-keyed hash table instead of
 * writing a second, pointer-keyed hash table implementation from scratch
 * for what is deliberately a RARE fallback path, not a hot one — see
 * mojo_obj_getattr's own docstring on why this path is only reached when
 * codegen couldn't resolve the access statically). Lazily allocated. */
static MojoDict *_mojo_dynattr_objects = NULL;

static void _mojo_dynattr_key(void *obj, char *buf, size_t buflen) {
    snprintf(buf, buflen, "%p", obj);
}

int64_t mojo_obj_getattr(void *obj, char *attr) {
    if (_mojo_dynattr_objects) {
        char key[32];
        _mojo_dynattr_key(obj, key, sizeof key);
        int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
        if (handle) {
            MojoDict *attrs = (MojoDict *)(intptr_t)handle;
            if (mojo_dict_contains(attrs, attr))
                return mojo_dict_get_int(attrs, attr);
        }
    }
    mojo_raise_attribute_error(attr);   /* new — see Step 2 */
    return 0;  /* unreached: mojo_raise_attribute_error longjmps/raises */
}

void mojo_setattr(void *obj, char *attr, int64_t val) {
    if (!_mojo_dynattr_objects) _mojo_dynattr_objects = mojo_dict_new();
    char key[32];
    _mojo_dynattr_key(obj, key, sizeof key);
    int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
    MojoDict *attrs;
    if (handle) {
        attrs = (MojoDict *)(intptr_t)handle;
    } else {
        attrs = mojo_dict_new();
        mojo_dict_set_int(_mojo_dynattr_objects, key, (int64_t)(intptr_t)attrs);
    }
    mojo_dict_set_int(attrs, attr, val);
}
```

Rename the doc comment above `mojo_obj_getattr` (currently says "there is
no dynamic module/object system at runtime to look this up in" — no
longer true once this lands) and update `mojo_runtime.h`'s declarations'
own comments to match.

This intentionally does NOT free `attrs` dicts when `obj` is freed — this
codegen has no object-lifetime/refcounting/GC story anywhere else either
(confirmed: no `free()` calls paired with any struct allocator in
gimple_codegen.py's `_alloc_*` emission), so a leaked per-object dict is
consistent with the rest of this runtime's existing memory model, not a
new regression.

### Step 2 — real AttributeError on a missing dynamic attribute

`mojo_obj_getattr`'s current abort-with-fprintf behavior was appropriate
for "codegen bug, should never happen" — but a MISSING dynamic attribute
(`cls.__slot_names__` before it's ever been set) is exactly the case the
bug's own minimal repro handles with `try/except AttributeError`, which
this compiler's exception machinery already supports for other error
paths (see `raise-never-worked-exception-hierarchy-fix` in memory — a
real, working typed-exception system exists: `mojo_raise`/exception-
hierarchy matching). Add a small `mojo_raise_attribute_error(char *attr)`
helper (formats a real `AttributeError` message including the attribute
name, calls the same `mojo_raise`-family entry point every other typed
exception in this runtime uses) so `except AttributeError:` in compiled
code around a missing dynamic attribute genuinely catches it — this is
required for the bug's OWN minimal repro to behave correctly, not
optional polish.

### Step 3 — wire the two dispatch functions to use real storage

`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`'s fallthrough lines
(gimple_codegen.py:30336, :30341) already call `mojo_obj_getattr`/
`mojo_setattr` — Steps 1-2 make those calls do the right thing with **no
codegen change needed at all** for sub-cases A/B (opaque `cls`/`self`/
class-object values). This is the highest-leverage part of the plan.

### Step 4 — Sub-case C: route fixed-layout runtime structs through dynamic dispatch too

In the assignment-lowering `else` branch (gimple_codegen.py:16498-16502)
and the parallel read-side "known struct" branch, add a check: is
`node.target.member` (or `node.member` for reads) actually present in
`self.struct_field_types.get(struct_name, {})`? If not, AND `struct_name`
is one of this codegen's own fixed runtime-owned struct names (a small,
enumerable set — `MojoBoundMethod`, `MojoGenerator`, `MojoAsync`, and any
other struct this file itself defines in `_emit_struct_defs`/the runtime
headers rather than one arising from a user's `class` statement — these
are already distinguishable from user structs since user structs all
appear in `struct_field_types` via `StructDef` processing, never
hardcoded), fall back to the same `_mojo_dispatch_getattr`/
`_mojo_dispatch_setattr` call emitted for the opaque case instead of a
direct `->member` access. A **user-defined** class hitting an unknown
field should keep its existing behavior (grow the struct, per
`_collect_self_assigns`) — this new check must be scoped to the fixed-
layout runtime set only, not user structs in general, or it would silently
change today's (working) dynamic-field-growth behavior for ordinary Mojo
classes into a slower dict-backed path for no reason.

### Step 5 — verification

1. The minimal repro (`dynamic_attr_repro.mojo` above) — `python3 mojo.py
   build` compiles clean, and (new, since Step 2 makes this meaningful) a
   `run`-mode test confirms the `try/except AttributeError` branch
   actually fires on the first call and the `else` branch (fast path,
   attribute already set) is hit on a second call with the same `cls`.
2. `Tools/c-analyzer/c_common/clsutil.py`, `Lib/collections/__init__.py`,
   `Lib/ctypes/__init__.py`, `Lib/string/__init__.py` (+ `Lib/importlib/
   __init__.py` transitively) via `py314_harness.py`/direct `mojo.py
   build` — confirm each file's specific error from this doc is gone (a
   different, unrelated error is an acceptable outcome, per this
   session's established norm; a clean compile is the ideal one).
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   this touches a preamble helper emitted into every module compiled with
   `do_imports`/reflection support, so a regression here would be broad.
4. Add a `test_gimple.py` case for the AttributeError-on-missing-dynamic-
   attribute behavior specifically (Step 2) — this is genuinely new
   observable behavior (previously: silent 0; now: a catchable
   exception), not just "stops erroring at compile time".

### Risk

Low-to-moderate. Step 1-3 add a new runtime code path reached only when
the existing tag-dispatch already falls through (today: a warning + wrong
answer; after: real storage) — strictly additive, no existing passing
behavior should change. Step 4 is the riskier piece: the "is this struct
name one of the fixed runtime-owned ones" set must be enumerated
carefully (miss one → same compile error persists for that struct; over-
include a name that's ALSO sometimes used for a user struct — unlikely
given this codegen's struct-name collision guards (`_struct_name_owner`)
already prevent user/runtime name clashes, but worth double-checking
before implementing).
