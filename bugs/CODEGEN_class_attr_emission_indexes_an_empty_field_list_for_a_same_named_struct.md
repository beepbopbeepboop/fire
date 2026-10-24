# The class-attribute emission pass indexes an empty field list for a same-named struct

## Status 2026-10-24 — FIXED: a `continue` when the attribute is not declared in this struct's own fields

`gen_module_impl`'s class-attribute emission loop walks EVERY `StructDef`
in `all_struct_defs`, and for each attribute name registered under the
struct's name it computes

    _own_idx = _own_class_field_index(s.fields, aname)   # -1 when absent
    for _pick in range(_own_idx, _own_idx + 1):          # range(-1, 0) == [-1]
        field = _as_list(s.fields)[_pick]                # s.fields[-1]

`_own_class_field_index` returns `-1` when `aname` is not among the struct's
fields, and `range(-1, 0)` yields `[-1]`. For a struct whose `.fields` list
is EMPTY (a docstring-only / method-only class, or a same-home redefinition
with no class-level assignment), `s.fields[-1]` is
`IndexError: list index out of range`, and the whole build dies mid-codegen.

## Why the name-keyed registry conflates the pair

`self._class_attrs` is keyed by struct NAME only (`self._class_attrs[s.name]
= {}` ... `[aname] = mangled`). A same-named pair in one `all_struct_defs`
(two classes of one name, or one class redefined in its own file) therefore
shares one attribute map, and the emission loop walks every copy of the name
against it. The struct-identity pass (`_struct_cname_by_id`) renames only a
GENUINE cross-module collision (both homes known and different); a same-home
redefinition deliberately keeps the bare name (a Python redefinition — "the
second binding replaces the first" — is modeled by `_struct_name_owner`'s
first-wins), and that unrenamed, field-less copy is exactly what the emission
loop chokes on.

## Measured

- Minimal single-file shape — one module defining `class Box: tag = 1`,
  later redefining `class Box:` bare, reading `Box.tag` before the
  redefinition — on BOTH `566ba1c9` (master) and `8c48013c` (the row-16
  failed-import rollback): `driver.compile_program` dies with `IndexError:
  list index out of range` in this loop, no binary. The crash is a LATENT
  PRE-EXISTING bug on master.
- At scale, EXPOSED (not caused) by `8c48013c`: the row-16 rollback un-
  poisoned the self-import guard, so whole-program closures carry same-
  named class pairs into the shared stmt mirror and reach this loop.
  Measured, `Lib/importlib/resources/readers.py` (arm64, 8 GB ceiling, warm
  CAS): `8c48013c` alone produced 77+ `IndexError` tracebacks — every one
  this line — across `io`/`stat`/`genericpath`/`operator`/`keyword`/
  `types`/... (120+ `# ERROR ... list index out of range` lines,
  `build/remes/r03post.log`), while the pre-fix master probe of the
  IDENTICAL build finished in minutes, 0.9 GB, 23 clean content rejections,
  zero crashes. The crash-time enumeration printed from the loop itself:
  `s.name='_SelectorMapping' nfields=0` beside a non-empty
  `_class_attrs['_SelectorMapping'] = ['__slots__', '__class_getitem__',
  '__abc_tpflags__', '__reversed__']` — the `_collections_abc.Mapping`
  base's class attributes registered under the same name — and the closure
  carried `IOBase`/`Reader`/`Writer`/... 4 times each (the same file
  accumulated under multiple spelling keys).
- After the fix, the identical readers.py build (`build/remes/r03fix.log`):
  0 `list index out of range`, 54 clean deterministic rejections (the
  `next(...)` / `d.pop` / unterminated-string / generator-`.close()`
  classes), and the run now does REAL work — more of the closure actually
  compiles — until it breaches the 8 GB ceiling at 8.7 GB (rc=125). Row 3's
  verdict moves from "fast deterministic rejection (0.9 GB)" to "RESOURCE
  8.7 GB @ 8 GB" — the importlib closure family's documented scale (its
  sibling, row 23's `importlib/metadata`, is the 31.6 GB runaway) — recorded
  on the roadmap, not chased here.

## The fix

`mojo/backend_gimple/module_gen.py`, the emission loop: when `_own_idx < 0`
(this object does not declare `aname`), `continue` — emit nothing for it.
The owning same-named struct (the one whose fields DO declare `aname`)
emits the attribute exactly once, as before. The non-empty-`fields` spelling
of the same case was already an implicit no-op in the old code (`fields[-1]`
cannot match `aname`, so the body did nothing); only the empty-list spelling
was live, and it was the crash.

Regression: `test_link_mode.py::test_class_redefinition_does_not_crash_class_attr_emission`
(the minimal single-file shape): FAILS before on both `566ba1c9` and
`8c48013c`, PASSES after — the binary prints `1` == CPython, which also pins
the REAL value: had the fix dropped the attribute instead of emitting it
from the owner, the program would print `0`. `test_link_mode.py` 19/19 on
the fixed tree.

## Related pre-existing gap, NOT touched here

Two DIFFERENT modules each defining `class Box` (a genuine cross-module name
collision) fail identically on all three trees — master, `8c48013c`, and the
fixed tree — at a different site, in two shapes:

- `box_0.py` (attr-less `Box`) + `box_9.py` (`Box` with `tag`), imported in
  sort order: the build dies in GCC with `main.py:4:9: implicit declaration
  of function 'box_0_Box_m_a'; did you mean 'box_9_Box_m_a'?` — the call
  site for `BoxA().m_a()` (BoxA from `box_9`) resolved through the OTHER
  copy's qualified cname.
- The reverse name order (`box_a.py` first, `box_b.py` last): the build
  LINKS, but the binary exits 1 with no output where CPython prints `1 b a`
  — the value read silently wrong, a worst-case shape.

The identity pass's cross-module branch mints a qualified cname for the C
TYPE, but the name-keyed home-claim maps (`_imported_struct_home` /
`_imported_func_home`, first-wins per NAME) and the name-keyed
`_class_attrs` registration still conflate the copies, in whichever way the
name ordering falls. Feature-sized (per-cname maps, or per-cname emission);
the next step for a separate item, not chased in this one.
