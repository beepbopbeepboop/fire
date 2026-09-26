# CODEGEN_dynamic_attribute_string_reads_as_pointer: a dynamically-set attribute's string value reads back as a raw int64 pointer in the compiled path

## Status (2026-09-26, first entry — bug ISOLATED and REPRODUCED, NOT fixed; it is the leading suspect for `make bootstrap`'s 44-file `#line` divergence, but that link is NOT yet proven)

Found while triaging `make bootstrap` on `f6837c8` (see "Relationship to
`make bootstrap`" below). Reproduced in a self-contained 6-line program, so
it is not an artifact of the bootstrap's scale.

### The bug

```mojo
class C:
    pass

def main():
    o = C()
    o.x = "hello"
    print(getattr(o, "x", ""))
    print(o.x)

main()
```

- CPython: `hello` / `hello`
- compiled: `16235256` / `16235256`

Both the 3-argument `getattr` and the plain attribute read return the raw
`char *` **as an int64_t**, which the print path then formats as a decimal
address. The write itself is fine — the value really is stored, and it
round-trips through every other accessor; only the *type* presented to the
caller is wrong.

Also confirmed while narrowing it: a 3-argument `getattr` whose key is
**absent** does not reliably return the supplied default. A parameter is
also still treated as capturing-by-default in the lambda lifter whenever its
name is visible in `var_types` (fixed in `fce5798`, but recorded here
because the same visibility rule is what makes this class of bug hard to
see).

### Why it happens

A dynamically-set attribute has no static C type, so the codegen cannot
know the stored value is a string. The compiled `getattr`/member-read path
resolves the attribute through the runtime's per-object dynamic-attribute
dict (`mojo_obj_getattr`, `_mojo_dynattr_objects` in
`runtime/fire_runtime.c`), which returns a boxed `int64_t`, and the
codegen hands that straight back as `_boxed_ft` (see the
`_known_field_type` / `_boxed_ft` resolution in
`mojo/backend_gimple/emit_calls.py`'s `getattr` branch). Nothing in that
path consults the runtime discriminator the rest of the model already
relies on — `mojo_boxed_is_str` ("pointer-shaped and not a live registered
`MojoList` ⇒ string"), which `mojo_cstr_or_int_str` (added in `fce5798`)
and the repr walkers use.

### Candidate fix (not applied)

Dispatch the *comparison/typing* on the runtime discriminator at the point
the value is read, the way the repr helpers do, rather than letting the
static type decide. Concretely: a runtime helper that returns the value
already coerced for the requested static type (e.g.
`mojo_dynattr_get_as(v, want)`), used only on the dynamic-attribute path so
struct-typed reads keep their exact typing. This is deliberately NOT done
blindly — every dynamic-attribute consumer is affected, so it needs the
full gate (below) per iteration, and it is the kind of change that can
silently re-type a value that some other site was (accidentally) relying on
being an integer.

## Relationship to `make bootstrap`

`make bootstrap` on this tree's base commit now **runs to completion**: no
`SIGTRAP`, and **zero** dump failures across all three stages. Its `verify`
step reports 136 files byte-identical and 44 `.ci` files differing — and
**every one of the 44 is `stage1 vs stage2`; there is not a single
`stage2 vs stage3` failure.** So the self-hosted binary is deterministic
and reproduces itself exactly, and the whole divergence is
python-reference vs native, in one direction.

That 44-file divergence is a single systematic difference:

```
stage1/hello.ci:1155: #line 2 "../hello.mojo"
stage2/hello.ci:1155: #line 2
```

The native path emits a bare `#line N` with no filename, i.e.
`gen._current_filename` is empty in the self-hosted build, so
`gen_stmt`'s `getattr(gen, '_current_filename', '')` yields nothing. The
entire `hello.ci` diff is 48 lines, all of them `#line` directives.

**This is where the isolation above was done, and the honest state is that
the link is NOT established.** Note the symptom does not line up cleanly
with the bug as isolated: a raw pointer is *truthy*, which would produce
`#line 2 "<decimal>"`, not a bare `#line 2`. So either there is a second
step (an empty-string read rather than a pointer read) or the filename is
lost earlier — e.g. the argument not surviving the call into
`gimple_codegen.compile_to_gimple(src, do_imports=False, filename=...)`
from compiled `fire.py` (a cross-module call with a keyword argument;
keyword arguments were verified to work for same-module calls, and the
cross-module probe was inconclusive because the probe program itself turned
out to be invalid). Ruled out so far: the arity/keyword call path for
same-module functions, and the `gimple_codegen_compile_to_gimple` C shim in
`runtime/fire_runtime.c` (it does forward `filename`).

This supersedes nothing in
`CODEGEN_noshim_dumpfull_preexisting_divergence.md`; that doc's 14-file
`verify` failure is the same stage1-vs-stage2 shape and this entry is the
current, narrower measurement of it.

## Also open, found in the same session, independent of the above

1. **Imported-function prototypes go missing in the full self-host build**
   (introduced by `fce5798`, i.e. by this session's lambda-capture work):
   `make check-selfhost` fails with
   `assignment to 'char *' from 'int'` and
   `implicit declaration of function 'cas_lookup_1b532c'` inside LIFTED
   CLOSURES. A baseline worktree at the parent commit was green, and
   compiling `driver.py` standalone still emits all 30 `cas_*` declarations
   correctly — so it is an ordering interaction that only appears in the
   full build. Leading suspect: the new env-struct `typedef` is appended to
   `gen._elaborated_externs`, the same list the imported-function
   prototypes go into, from a different point in the emission order.

2. **Cross-module calls returning 0** — an unverified lead, recorded so it
   is not re-derived from scratch. The probe that suggested it was itself
   invalid (the interpreter also returned 0 for it), so treat it as
   unconfirmed.

3. **The two key-function gaps** deliberately left documented in
   `_lower_builtin_sorted_keyed` rather than papered over: a
   dict-subscripted global read inside a lifted lambda returns 0, and an
   **unannotated named function** handed a string element misreads it
   (`key=bylen` where `def bylen(s): return len(s)` gives lengths 2,3,1
   instead of 1,2,3 — correct when the same function is called directly). A
   lambda key and a builtin key both handle string elements correctly.

4. **`zip()`'s pair shape is deliberately left untyped.** The pairs print as
   tuples now, but `_lower_builtin_zip_n` still returns `void *` and records
   no element type, because typing it breaks a real self-host shape (a
   comprehension with a nested tuple target over `zip` reads a 2-slot pair
   spec and then indexes a list where a string was expected). The repr-only
   routing added in `fce5798` was an attempt to fix the printing without
   that hazard and has since been REMOVED in favour of the generated
   `_mojo_repr_pair`, which needs no metadata at all.

5. **`map`/`filter` with more than one iterable** are an honest refusal, not
   an implementation (`map(f, xs, ys)`).

## Gate required before any of this is called fixed

Per `CLAUDE.md`, none of the above is trustworthy on a partial run. A fix
landing here needs: `make check-linkmode`, `make check-selfhost`, a
from-scratch stdlib dylib build (skip count must not rise),
`python3 compile_stdlib.py` (`U` must not rise), `make bootstrap`, and
`make check-native-dumpfull`. Bootstrap and native-dumpfull are the two
steps that exercise the self-hosted binary's own codegen — every other step
drives the python3-interpreted reference, which is structurally blind to
exactly the class of bug in this document.
