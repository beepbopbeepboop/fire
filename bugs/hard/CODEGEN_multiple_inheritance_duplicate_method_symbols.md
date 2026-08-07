# HARD BUG: a class with multiple inheritance and no methods of its own gets every inherited method emitted twice

## Status

Unfixed, not fully root-caused (leading hypothesis below, not verified
against the generated C). Found 2026-08-06 investigating
bugs/COMPILE_FAIL_importlib_abc.md. Not attempted given time — this is a
structural gap in the struct-inheritance merge/emission pipeline, likely
needs careful tracing through `all_struct_defs` construction across
module boundaries to confirm, not a narrow fix.

## Symptom

Roughly 20 `redefinition of 'abc_{ClassName}_{method}'` GCC errors in a
single file, all tracing to TWO classes:

```python
class FileLoader(_bootstrap_external.FileLoader, ResourceLoader, ExecutionLoader):
    """Abstract base class partially implementing the ResourceLoader and
    ExecutionLoader ABCs."""
    # (no methods of its own — pure multiple-inheritance combinator)

class SourceLoader(_bootstrap_external.SourceLoader, ResourceLoader, ExecutionLoader):
    """..."""
    def path_mtime(self, path): ...
    def path_stats(self, path): ...
    # (plus its own methods; also inherits get_data/is_package/get_source/
    #  source_to_code/get_filename/get_code from its 3 bases, same as FileLoader)
```

Both classes use MULTIPLE INHERITANCE from the same base set
(`ResourceLoader`, `ExecutionLoader`, plus a same-named class imported
from another module — `_bootstrap_external.FileLoader`/`SourceLoader`).
`FileLoader` has NO methods of its own at all — every method it has
comes from a base class.

## Leading hypothesis (not fully confirmed)

`_merge_struct_inheritance` (gimple_codegen.py:1638) merges each base's
`.methods` into a class's own `.methods` list, keyed by method NAME
(`merged_methods[m.name] = m`, later bases override earlier ones for
same-named methods — this part looks correctly deduplicated per class).
For a class like `FileLoader` with an EMPTY own-method list, `inherited =
[m for name, m in merged_methods.items() if name not in own_names]`
evaluates to essentially ALL of `ResourceLoader ∪ ExecutionLoader`'s
methods (own_names is empty), so `s.methods` ends up large — a full
copy of every inherited method, not just the couple the class actually
overrides.

The actual C-symbol EMISSION step (elsewhere in gen_module, not
inspected in this session — not yet located precisely) presumably walks
`all_struct_defs` (or an equivalent whole-program struct list) emitting
`abc_{StructName}_{MethodName}` for every struct × its (now much larger,
inheritance-inflated) `.methods` list. If `all_struct_defs` contains a
DUPLICATE entry for `FileLoader` (or `SourceLoader`) — plausible given
`do_imports=True`'s whole-dependency-graph compilation, where a class
could be independently discovered once via this module's own top-level
scan and again via some cross-module resolution/import path that isn't
correctly deduplicating BY IDENTITY (or by module-qualified name) — then
its ENTIRE inflated methods list (now full of inherited methods, per the
above) would get emitted TWICE, producing exactly the volume and pattern
of "redefinition" errors observed (every inherited method redefined
once, for exactly the two classes that have large multiple-inheritance-
derived method lists).

This is NOT yet verified against the actual generated C (would need to
find and read the real struct/method emission loop and check whether
`all_struct_defs` genuinely double-counts `FileLoader`/`SourceLoader`) —
flagged as the most likely explanation given the evidence, not a
confirmed root cause.

## Separate, already-tracked issue in the same file

```
error: expected identifier before '__func__'
```
at:
```python
if self.path_stats.__func__ is SourceLoader.path_stats:
    raise OSError
```
`self.path_stats.__func__` (accessing a bound method's underlying
function object) is a dynamic-attribute-on-generic-object case, already
covered by bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
Sub-case C (`MojoBoundMethod` dunder-attribute access) — not a new
finding, just confirming another instance.

## What a real fix needs

1. Confirm or refute the duplicate-`all_struct_defs`-entry hypothesis by
   locating the actual struct/method C-emission loop and instrumenting
   or reading it directly against this file's real compile.
2. If confirmed: dedupe `all_struct_defs` by struct NAME (or better, by
   module-qualified name, consistent with how this codebase already
   dedupes free functions elsewhere — see `_struct_name_owner`, an
   EXISTING same-bare-name collision guard referenced in
   bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md —
   check whether that mechanism is supposed to cover this case already
   and isn't, or whether this is a genuinely different code path it
   doesn't reach).
3. If NOT confirmed (some other cause): re-investigate from scratch,
   likely by minimally reproducing with a small multi-inheritance-only
   repro file (two ordinary classes `A`/`B` with disjoint methods, a
   third class `C(A, B)` with no methods of its own) and inspecting the
   generated `.ci` directly for duplicate `C_methodname` definitions.

### Risk

Unknown until the root cause is confirmed — could range from a narrow,
low-risk dedup fix (if it's really just a duplicate-list-entry bug) to
something touching the shared inheritance-merge machinery broadly (if
the fix needs to change `_merge_struct_inheritance` itself, which many
other structs' correctness depends on). Verify with the full 5-part
quality gate regardless.
