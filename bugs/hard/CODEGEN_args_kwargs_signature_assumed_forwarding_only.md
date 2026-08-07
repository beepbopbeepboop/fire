# HARD BUG: a function declared `(*args, **kwargs)` assumes every call site uses spread syntax, breaking ordinary positional calls

## Status

Unfixed. Root-caused 2026-08-06 while investigating
bugs/COMPILE_FAIL_ctypes___init__.md. This is a DELIBERATE, DOCUMENTED
design tradeoff in existing code (not an oversight) that turns out to be
wrong for a real, common calling pattern — fixing it requires care not to
regress the case it WAS designed for. Not attempted here given the
architectural scope and the demonstrated risk of hasty changes to this
exact area (see bugs/COMPILE_FAIL_collections___init__.md's `_tuplegetter`
investigation from the same session — two fix attempts elsewhere in the
call-lowering machinery both caused broad compile_stdlib.py regressions
before being reverted).

## Symptom

```
error: too many arguments to function 'make_thing_07077a'; expected 3, have 4
```

## Minimal repro

```python
def make_thing(restype, *argtypes, **kw):
    return len(argtypes)

def main():
    print(make_thing(1, 2, 3, 4))

main()
```

`python3 mojo.py build` — fails with the arity error above.

## Real-world file exposing this

`Lib/ctypes/__init__.py`:
```python
def CFUNCTYPE(restype, *argtypes, **kw):
    ...
memmove = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_size_t)(_memmove_addr)
```
— `CFUNCTYPE` called with 4 ordinary positional arguments (1 `restype` +
3 real `argtypes`), not spread syntax.

## Root cause (confirmed)

`_signature_ctypes` (gimple_codegen.py:19985), which computes a
function's C parameter-type list, has a DELIBERATE special case:

```python
has_kw = any(pn.startswith('**') for pn, _ in (params or []))
...
elif pn.startswith('*'):
    if has_kw:
        out.append('MojoList *')      # pass-through: concrete list param
    elif not seen_vararg:
        out.append(sentinel)          # packing convention
```

Its own docstring explains the intent: "`*args -> 'MojoList *'` when the
function ALSO has `**kwargs` (the forwarding pattern `f(self, *args,
**kwargs)`: the parser flattens the call's spreads, so the caller passes
the list/dict directly -> concrete params, no packing)." I.e. this
codegen assumes that whenever a function's signature has BOTH `*args`
AND `**kwargs`, EVERY call site looks like `f(*a, **k)` (spread syntax,
where `a`/`k` are already a real `MojoList *`/`MojoDict *` the caller
built or received) — so the callee's OWN `*args` parameter is typed as a
plain concrete `MojoList *` (no packing sentinel), and `_emit_call`
(gimple_codegen.py:5436, `if param_types and param_types[-1] == '...':`)
never packs anything for such a call, because a `**kwargs`-having
function's param list never ends in the `'...'` sentinel in the first
place.

This assumption is correct for the SPREAD-FORWARDING idiom it was built
for (confirmed: real code like a wrapper method that does `return self.
_impl(*args, **kwargs)` inside its OWN body) — but WRONG whenever a
`(*args, **kwargs)`-declared function is instead called with ordinary,
literal positional/keyword arguments (`CFUNCTYPE(c_void_p, c_void_p,
c_void_p, c_size_t)`, no spreads at all). In that case the callee's
`*argtypes` parameter is still typed as a bare `MojoList *` (matching the
"has_kw" branch), the caller's extra positional arguments are NOT packed
into a list at all, and they're instead coerced 1:1 against whatever
concrete param types happen to be at those positions (`argtypes` gets one
raw scalar wrongly pointer-cast to `MojoList *`, `kw` gets the NEXT raw
scalar wrongly cast to `MojoDict *`, and any further arguments are passed
as raw, un-consumed EXTRA C arguments) — producing the "too many
arguments" arity mismatch (or, in cases where the counts happen to align,
a SILENT type-confusion bug instead of a compile error).

Note this is a DIFFERENT (though related) issue from the ALREADY-KNOWN
"packing sentinel gets overwritten after body generation" bug documented
inline at gimple_codegen.py:5411-5430 (partially worked around there via
`_mangled_signature_ctypes` for struct methods) — that one is about a
genuinely-packable `*args`-only (no `**kwargs`) function losing its
sentinel due to registration-order timing. THIS bug is about the
`has_kw=True` case, where packing is intentionally disabled REGARDLESS of
timing, because of the forwarding-only assumption above.

## What a real fix needs

The two calling conventions (spread-forwarding vs literal positional
args) need to be disambiguated PER CALL SITE, not baked into the callee's
signature alone — the callee's own declared shape (`*args, **kwargs`)
looks identical either way; only the CALL EXPRESSION's own shape
distinguishes them (does the call site literally write `f(*a, **k)`, or
does it write `f(1, 2, 3, x=4)`?).

1. At each call site, check whether the call's OWN arguments include an
   explicit spread (`*expr`) — this codegen already detects spreads
   elsewhere (`_lower_list_literal`'s `_is_spread` helper is the closest
   existing pattern, though that's for list literals specifically, not
   call arguments — check `mojo_compiler.py`'s CallExpr AST for how a
   `f(*a)`-shaped call already represents the spread argument, since some
   mechanism must already parse it given the "parser flattens the call's
   spreads" comment implies this is understood elsewhere).
2. If the call site uses a real spread, keep today's behavior (pass the
   already-packed list/dict through, unchanged — this is the case
   `_signature_ctypes`'s `has_kw` branch was correctly built for).
3. If the call site instead has ordinary positional/keyword arguments
   (no spread), pack the EXTRA positional arguments (beyond the callee's
   named, non-star params) into a real `MojoList *` at the call site
   (mirroring `_emit_call`'s EXISTING packing logic for the
   `has_kw=False` sentinel case, gimple_codegen.py:5436-5446 — the
   mechanism to reuse already exists, it just needs to also fire for the
   `has_kw=True` callee shape when the CALL SITE itself isn't a spread
   call) and pack keyword arguments into a `MojoDict *` similarly.
4. `_signature_ctypes`'s callee-side typing can likely stay AS-IS (a
   `*args`-with-`**kwargs` param is always `MojoList *`/`MojoDict *`
   concretely at the C level either way) — the fix belongs entirely on
   the CALL-SITE lowering side, which needs its own "is this call
   actually a spread-forward, or literal args that need packing"
   decision, independent of what `_signature_ctypes` says about the
   callee.

### Verification

1. The minimal repro above (both compile AND run — `len(argtypes)` must
   equal 3, not crash or misbehave).
2. A genuine spread-forwarding call (`def wrapper(*a, **k): return
   inner(*a, **k)`) must be UNCHANGED/still correct — this is the
   existing, presumably well-exercised case; don't regress it.
3. `Lib/ctypes/__init__.py`'s own `CFUNCTYPE`/`memmove`/`memset`
   real-world trigger compiles clean.
4. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   this touches core call-argument-lowering machinery used everywhere;
   given this exact area caused two broad regressions earlier this
   session from seemingly-safe changes, treat ANY test_gimple.py/
   test_module_cache.py pass as necessary but NOT sufficient — the full
   664-file compile_stdlib.py run is the real gate here, every time.

### Risk

High for the reasons above — this is call-argument-lowering machinery
with a documented history of regressions from confident-looking fixes in
this exact area. Recommend prototyping the fix, then running
compile_stdlib.py -j8 BEFORE spending time on more verification, to get
the highest-signal check first and fail fast if the fix has the same
shape of unintended blast radius as the two reverted `_tuplegetter`
attempts.
