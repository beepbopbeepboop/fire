# COMPILE_FAIL: Lib/importlib/resources/readers.py

## Status (updated 2026-08-26 — fresh deep-dive per task request; doc remains OPEN, but the documented blocker text is now substantially stale and the remaining gap is precisely characterized)

Fresh investigation this session, as explicitly requested (the recent
generator value-carrying-return work prompted a re-check of whether
cross-generator `yield from` delegation is now plausibly tractable).
Reproduced today's isolated refusal — same two shapes, byte-for-byte:

```
Unsupported shape(s): _candidate_paths: _candidate_paths: a
@classmethod generator that references `cls` in its body in an
unsupported way (...); _resolve_zip_path: unsupported for-loop
iterable type: CallExpr.
```

### What changed since the 2026-08-25 write-up (stale-text corrections)

1. **Cross-generator delegation is NO LONGER "a real, separate,
   not-yet-built mechanism" in general.** The old text's premise is now
   only ~half true. Verified fresh via minimal repros against current
   master:
   - `yield from <plain-name>(...)` delegating to another compiled
     free-function generator WORKS (`_generator_api` + fixed-point
     retry passes for forward references);
   - `for x in self.<genmethod>(...)` / generator-METHOD delegation
     WORKS (`_generator_method_api`, receiver passed as literal
     `self`);
   - @classmethod generators with receiver passing WORK; and,
     notably discovered this session: **@staticmethod generators are
     silently routed through the FREE-FUNCTION generator path**
     (gimple_module_gen.py's free-fn loop skips only first-param-
     self/cls functions), compiling to a module-unqualified
     `_mojogen_<name>_*` unit registered under their bare name. A
     minimal repro confirms `_resolve_zip_path`'s trivially-reduced
     body (plain string yields) compiles fine standalone.
2. **The "plain `yield` of a foreign-module constructor" half of the
   old blocker is GONE.** `yield pathlib.Path(path_str)` inside a
   generator body now compiles (verified with an isolated probe).

### What ACTUALLY remains missing for `_candidate_paths`

Exactly one narrow thing: `_cls_refs_supported` deliberately excludes
`cls.<method>(...)` when `<method>` is a generator method of the
enclosing struct, and `_cpp_yield_from`'s delegation dispatcher has no
branch resolving a `cls.` receiver (it handles bare IdentExpr callees
and literal-self receivers only). A minimal two-method repro (classmethod
generator doing `yield from cls.<staticmethod-gen>(...)`) refuses at
eligibility even though the staticmethod callee itself fully compiles.
Extending it would be: relax the exclusion for generator methods that
have (or, via the existing retry passes, will get) an api entry, plus a
`cls.`-receiver branch in the yield-from/for-consumption emitters
(staticmethod callee → no receiver arg; classmethod callee → opaque
int64_t placeholder, mirroring `_gen_cpp_generator_unit`'s own `('cls',
'int64_t')` convention). Plausibly a small, mechanical change.

### Why it was nevertheless NOT attempted, and why this doc stays open

Fixing delegation alone cannot close this file, because
`_resolve_zip_path` independently refuses on shapes that are genuinely
feature-sized:
- `for match in reversed(list(re.finditer(r'[\\/]', path_str)))` —
  CallExpr iterable still refused (re-probed fresh); and beneath that,
- `match.end()`/`match.start()` are calls on `re.Match` objects
  produced by the CPython C-extension `_sre` engine — there is no
  compiled representation of them anywhere in this pipeline (re itself
  falls back to source interpretation during the build), so consuming
  them inside a coroutine frame would need a foreign/interpreted-object
  model the scalar-only coroutine codegen deliberately does not have;
- the guarded body runs under `with contextlib.suppress(...)` whose
  exception-suppression semantics the plain-generator path currently
  ELIDES entirely (documented convention) — acceptable only because
  nothing here can represent the suppressed exceptions anyway.

Also relevant to the cost/benefit: `grep -rn "yield from cls\."`
across the entire Lib/ tree hits exactly ONE site — this file's line
162. The narrow delegation extension would have zero other consumers
today, and it edits shared coroutine eligibility/emission machinery
(the exact class of change CLAUDE.md's regression history warns
about). Per the campaign's risk policy — don't touch shared machinery
without end-to-end payoff — deferred until some real consumer can
actually compile end-to-end once it exists.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, unchanged, root cause pinned down precisely)

Re-ran an isolated `compile_to_gimple_with_cpp` check fresh (post this
session's coroutine-emitter fixes for COMPILE_FAIL_Apple___main__.md
— none relevant to this file's shape). The refusal message is more
detailed than the 2026-08-23 entry recorded (this file was evidently
last checked before `fd909e9`'s per-function refusal-reason reporting
landed), and pins down the exact mechanism:

```
Unsupported shape(s): _candidate_paths: _candidate_paths: a
@classmethod generator that references `cls` in its body in an
unsupported way is not supported (only a class-level-attribute read,
or a call to a real compiled classmethod/static method of the
enclosing class, are supported for `cls.<...>` access in a compiled
generator); _resolve_zip_path: unsupported for-loop iterable type:
CallExpr.
```

Read `gimple_cpp_core.py`'s `_cls_refs_supported` (the check that
produces this message): its own docstring/inline comment explicitly
and deliberately excludes a `cls.<method>(...)` call when `<method>`
is ANOTHER COMPILED GENERATOR (checked via `gen.
_struct_generator_method_names`) — exactly `_candidate_paths`' own
`yield from cls._resolve_zip_path(path_str)` shape (`_resolve_zip_path`
is itself a generator, a `@staticmethod`). The comment states plainly
this needs "its own coroutine-construction call convention this fix
does not add" — i.e. composing/delegating into another already-
compiled coroutine from inside a coroutine body is a real, separate,
not-yet-built mechanism, not a missing case in an existing dispatcher.
Separately, `_resolve_zip_path` itself additionally fails the for-loop
iterable check (`for match in reversed(list(re.finditer(...))):` —
`reversed(list(...))` as a for-target has no coroutine-body for-loop
lowering). Even fixing the for-loop gap alone would leave
`_candidate_paths` still refused by the `yield from`-into-another-
generator gap. Both genuinely feature-sized (coroutine-to-coroutine
delegation, a new call convention); not attempted. Doc kept open.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C4 cluster. The blocker (`_candidate_paths`: a plain `yield` of a foreign-module constructor followed by `yield from` delegating to another classmethod generator) is unaffected by this session's two landed fixes elsewhere (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still structural; untouched.


Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-23 against master 626f3f0 — unchanged, STILL-OPEN structural)

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
importlib/resources/readers.py` fresh: still fails with the IDENTICAL
up-front refusal, byte-for-byte the 2026-08-09 message —
`cannot compile module: function(s) _candidate_paths (generator
function(s), contain a yield/yield from)`. Although the compiled-
generator project landed substantial coroutine-body support since the
last pass (C++20-coroutine units for many shapes; this cluster's own
fd909e9 tightened its refusal contract), `_candidate_paths` remains
outside every supported shape and is refused by the module-level
pre-pass before any per-function codegen. The gap is exactly as the
2026-08-09 analysis below describes: a plain `yield` of a constructed
value (`yield pathlib.Path(path_str)` — a foreign-module constructor,
itself unsupported in the scalar body model) followed by `yield from`
delegating to another generator METHOD (`cls._resolve_zip_path`, a
@classmethod generator call needing the classmethod-generator
call-convention machinery). Feature-sized, not attempted; see that
write-up for the full shape requirements.

## Status (re-verified 2026-08-09 — historical): blocker changed, now a confirmed structural gap

Re-ran `python3 fire.py build .../readers.py` fresh against current
master. The 2026-08-06 blocker below (the `NamespaceReader.__init__`
unannotated-param `int64_t` mistype) no longer surfaces — presumably
fixed as a side effect of other recent type-inference work on sibling
importlib files this session — but the module still fails to build,
now on an earlier, module-wide pre-pass:

```
Error building: cannot compile module: function(s) _candidate_paths
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ... falling
back to interpreting this module from source instead
```

Confirmed real: `MultiplexedPath._candidate_paths` (line 160) is a
genuine generator —
```python
@classmethod
def _candidate_paths(cls, path_str: str) -> Iterator[abc.Traversable]:
    yield pathlib.Path(path_str)
    yield from cls._resolve_zip_path(path_str)
```
`gimple_codegen.py`'s `gen_module` (`gimple_codegen.py` around line
30564) does an upfront, whole-module scan for any function containing
`yield`/`yield from` or declared `async def`, and — when not running
under `relaxed_imports` (stdlib-build fallback mode; `fire.py build`
on a direct entry file always runs strict) — raises immediately,
before any per-function codegen (including whatever
`NamespaceReader.__init__` now does) is even attempted. This is the
same well-known, deliberate limitation noted in this project's
generator/coroutine codegen history: only specific, narrow generator
shapes have a real suspend/resume state-machine lowering implemented
(see `test_generators.py`/the compiled-generator-codegen project in
git log); arbitrary generator shapes like this one (plain `yield` +
`yield from` delegating to another generator method) are not among
them. This is a genuinely structural gap, not a narrow bug — no fix
attempted here, per the task's explicit scope (generator support is
feature-sized, not a narrow fix).

## Status (updated 2026-08-06, historical — superseded above)

Re-ran; current error:

```
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:142:1: error: non-trivial conversion in 'mem_ref'
```
at `NamespaceReader.__init__`'s `self.path =
MultiplexedPath(*filter(bool, map(self._resolve, namespace_path)))`.

Root-caused: this is a confirmed real-world instance of the
already-documented hard bug
`bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md` (which
supersedes the removed
`CODEGEN_unannotated_init_param_field_type_defaults_int64.md`)
— `__init__(self, namespace_path)`'s unannotated `namespace_path`
parameter defaults to `int64_t` regardless of the real (iterable)
argument type. Confirmed via the generated `.ci`: the parameter is
declared `int64_t`, and an unrelated use of it a few lines earlier
(`if 'NamespacePath' not in str(namespace_path)`) lowers `str(
namespace_path)` as `mojo_str_from_int(namespace_path)` — the same
"real value is a container/string, field typed int64_t" signature the
hard bug doc's own minimal repro produces. `map(self._resolve,
namespace_path)` then tries to iterate the wrongly-int64_t-typed
param, producing the GIMPLE `mem_ref` conversion error. Added as a new
confirmed instance to that hard-bug doc. Not fixed here, per that
doc's own risk assessment (shared call-site/parameter type-inference
machinery, high risk, not attempted this session).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function '_alloc_MultiplexedPath':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:73:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   73 |         self._paths = list(map(_ensure_traversable, remove_duplicates(paths)))
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'remove_duplicates_0c85c9':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:260:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader___init__':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:34:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   34 |     def files(self):
      | ^   
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:32:7: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   32 |         return str(self.path.joinpath(resource))
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   31 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:30:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   30 |         copy.
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:28:11: warning: variable '_t5' set but not used [-Wunused-but-set-variable]
   28 |         Return the file system path to prevent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:27:10: warning: variable '_t4' set but not used [-Wunused-but-set-variable]
   27 |         """
      |          ^~ 
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:26:11: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   26 |     def resource_path(self, resource):
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:25:10: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
   25 | 
      |          ^  
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:24:11: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   24 |         self.path = pathlib.Path(loader.path).parent
      |           ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_resource_path':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:38:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   38 | class ZipReader(abc.TraversableResources):
      | ^~~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:31:7: warning: variable '_t3' set but not used [-Wunused-but-set-variable]
   31 |         """
      |       ^ ~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:29:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
   29 |         `resources.path()` from creating a temporary
      |          ^~~
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py: In function 'FileReader_files':
/Users/mrs/net/Python-3.14.6/Lib/importlib/resources/readers.py:39:1: warning: label 'bb_2' defined but not used [-Wunused-label]
... (1120 more lines)
```

Exit code: 1
Elapsed: 10.35s
