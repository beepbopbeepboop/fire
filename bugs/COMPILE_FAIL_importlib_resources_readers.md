# COMPILE_FAIL: Lib/importlib/resources/readers.py

## Status (updated 2026-08-26, worktree fix/opencode-group4 — re-verified fresh, unchanged)

Fresh isolated check reproduces the identical two-shape refusal:
`_candidate_paths` (classmethod generator referencing `cls` via a
delegating `yield from cls._resolve_zip_path(...)` into another
generator) + `_resolve_zip_path` (`for match in reversed(list(
re.finditer(...))):` for-iterable). Both remain the feature-sized gaps
analyzed below: coroutine-to-coroutine delegation through a classmethod
receiver needs the generator-method call convention wired into
`_cpp_yield_from`'s delegation (the api registries exist —
`_generator_method_api['base']`, `_struct_generator_method_names` — but
no consumer builds the drive loop for this shape), and the
reversed(list(...)) iterable has no lowering. Additionally, even past
both, `_candidate_paths`'s `yield pathlib.Path(path_str)` needs
foreign-module struct-construction yields to resolve Path's layout in
the whole-program build. Doc kept open.

## Status (updated 2026-08-25 -- re-verified against fix/rest-remainder12, superseded above)

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

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
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

Re-ran `python3 mojo.py build .../readers.py` fresh against current
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
under `relaxed_imports` (stdlib-build fallback mode; `mojo.py build`
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
`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
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
