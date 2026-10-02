# FORMAL_field_access_refusal_names_the_wrong_module: the refusal is about a variable, and the advice names a declaration the reader does not have

**Area:** CODEGEN/FORMAL (arm64 + x86-64): `formal/model.py`'s
`field_access_refusal`, reached from both emitters' slot-allocator
fall-through. Diagnostic only — **nothing is silently wrong**, and the
refusal itself is the behaviour this backend wants.

## What I ran

A struct library built with `fire.py dylib --formal`, its manifest's
`source` then pointed at a file that no longer exists (the case a
dylib shipped without its sources produces, and the one
`bugs/FORMAL_link_dylib_imported_struct_field.md` §"A narrower, honest
interim" asks about), and a program with NO import statement:

```console
$ python3 -c "…set manifest['source'] = '/nonexistent/heaplib.mojo'…"
$ python3 fire.py build --formal --no-prove -o prog2b.aout \
      --link-dylib gone/heaplib.dylib prog2.mojo
build: main: 'b.n' is a field access through 'b', and this path has no way to
say what 'b' holds. … 'b' is bound here as a parameter, so none of the three is
established … Bind the base from a constructor this module declares (`x = S()`),
or declare the field's type so the base is not typeless
```

`b` is not bound as a parameter. It is `var b = Bag()`, and `Bag` is
declared in the library's own source. The message's stated reason is
false about the program in front of the reader, and its repair is
impossible: `Bag` is not declared in this module and cannot be.

## Why it is not fixable where the message is written

`root` here is the **variable** (`b`), not the type (`Bag`), and the
only place the type appears is the binding `var b = Bag()` — which the
emitter's slot allocator does not see. `_no_home` is reached with a
slot key and nothing else.

I tried the obvious table: `formal/imports.py` deriving `{struct name:
install name}` from each linked library's `kind: "method"` exports (a
manifest carries `heaplib_Bag_add`, so it says `Bag` without needing the
source at all) and threading it to `field_access_refusal`. It does not
fire, because the name being asked about is `b`. The table was removed
rather than left in as dead weight; this doc is where it belongs.

## The exact next step

Answer it where the type IS known, which is the build pass, and refuse
there — a second, better-worded refusal for a program that is refused
either way is not a behaviour change:

1. In `formal/build.py`'s `check_construction_shapes` (the build-pass
   caller of `model.struct_construction_plan`), collect the set of
   names constructed with an EMPTY argument list: a `CallExpr` whose
   callee is an `IdentExpr`, whose name is in neither `_functions` nor
   `structs`, and which is a struct name some linked library exports a
   method for.
2. When that set is non-empty, emit
   `model.dylib_aliased_export_refusal`'s sibling for it: name the
   struct, the library that has it, and the two repairs that are
   actually available — rebuild the library where this build can read
   the module's source (so its manifest records one), or link the
   module by IMPORT (`from Bag import Bag`), which brings the
   declaration with it.
3. Do NOT suggest re-declaring the struct in the importing file. It
   would be a *different* type with the same name, and the frame the
   library's methods are called on would not be it — that is a silently
   wrong answer wearing the costume of a fix.

A narrower alternative that needs none of the above: change only the
existing last clause, so "Bind the base from a constructor this module
declares" is replaced by "Bind the base from a constructor whose
declaration this image can see — an import brings one with it, and a
`--link-dylib` library brings one if the source it was built from is
still readable". That is strictly better than today's sentence and needs
no new table, at the cost of not naming the library.

## What is NOT wrong here

With the source present, the whole shape works and is verified:
`b.n = 4`, `b.tag = 7`, `len(b)` (the `__len__` rewrite across the
boundary), `b.add(3)` and a second struct's `w.sum()` on
`--link-dylib heaplib.dylib` with no import statement all build, run, and
match CPython. That is `bugs/FORMAL_link_dylib_imported_struct_field.md`,
fixed in the same commit that filed this.
