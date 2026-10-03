# COMPILE_FAIL: Lib/socket.py — an unrelated grab-bag of compile gaps (title STALE)

## Status 2026-10-02 — the blocker did NOT move, and the census above it was short

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/socket.py` on
this tree: **exit 1**, and `Lib/enum.py:380` — the error the 2026-10-01 entry
reported as *the* blocker — is still there, unchanged, alongside **13 more in
the same file** and **fourteen imported modules** that fail in this closure.
The entry below read as if one error had replaced another; it had not. gcc
reports every error in the translation unit and the earlier census took the
first, so "the failure has moved" was an artefact of where the reading
stopped. This is the whole set, so nobody has to re-derive it:

**`Lib/enum.py` (14):** `380` ×2 (`mojo_list_len` / `mojo_list_get_str` on an
`int64_t` — `set(value) & set(self._member_names)` where `_member_names` is a
DICT, line 336, so `set(<dict>)` must yield its keys), `396`/`400`/`408`/`413`
(container-kind assignments both ways), `1093` ×2 (implicit declarations of
`Parameter___init__` / `Signature___init__`), `1624`-`1677` ×7 (`expected
expression before '(' token`), `1793` ×2 (`mojo_type` called with 3 arguments
where the runtime takes 1).

**Imported modules (14):** `_collections_abc`, `codecs`, `contextlib`, `dis`,
`gettext`, `inspect`, `pickle`, `re`, `re._compiler`, `traceback`, `types`,
`weakref` — all refused as ``next(...)`` on a shape the `next` lowering has
no case for (`next(IdentExpr)`, `next(MemberExpr)`, `next(CallExpr)`);
`typing.py` and `argparse.py` — container-kind coercions (`globalns`,
`args`); and two Mojo stdlib modules skipped for the same `next(MemberExpr)`
reason.

That is the honest size of this file: it is not one bug and it is not two.
`Lib/enum.py`'s metaclass body is `setattr` + descriptors + dynamic class
construction, and no part of the above is a single-cause fix.

**What did move, in the family this branch has been working:** none of it. The
multi-kind container fixes (`a3c9c090`, `73143dcb`, `fa85e923`, `0a6b1616`,
`d92a5a8c`) do not touch any of the fourteen — `typing.py`'s `globalns` and
`argparse.py`'s `args` are the same *shape* as `c_parser/match.py`'s
`expected`, but they are multi-kind for real (a local that is a list on one
branch and a dict on another), which is the case the BOX answers, and a box's
consumer needs a representation this backend does not have yet.

**Next step**, unchanged in substance: the individual gaps above, on their own
merits, with the `next(...)` family the largest — it accounts for twelve of the
fourteen imported modules, and its message already names its own supported
forms, so it is the one whose remaining work is best specified.

## Status 2026-10-01 — re-measured; past the entry below's blocker, and now failing inside `Lib/enum.py`

Fresh `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/socket.py` on
this tree: **exit 1**, and the failure has MOVED — it is no longer in `socket.py`
at all:

```
/Users/mrs/net/Python-3.14.6/Lib/enum.py:380:25: error: passing argument 1 of
'mojo_list_len' makes pointer from integer without a cast [-Wint-conversion]
  380 |   already = set(value) & set(self._member_names)
```

That is a real change from the 2026-09-30 entry, and worth naming what caused
it rather than leaving the next reader to re-derive it: the container-kind
coercion guard (`_sce_simple_emit`) plus the multi-kind-local and boxed-value
fixes landed after that entry now let `socket.py`'s own grab-bag of shapes
compile far enough that the closure reaches `Lib/enum.py`, which it did not
before.

**(The 2026-10-02 entry above corrects the reading of this one: `enum.py` was
always in the closure. See it for the full census.)**

`Lib/enum.py:380` is itself a `for`-target/`self._member_names` list-length
read on an `int64_t`-typed receiver — the boxed-value class. It was the same
shape as the dict-value-type gap this doc's 2026-10-01 entry cited (a value
whose real C type is known at the binding site but not at the use site), one
indirection further in; that dict half was FIXED on 2026-10-02 with
`_param_dict_val_types` (a dict's value type now crosses the call boundary),
so what is left here is the LIST-element-type axis of the same family, not
the dict one.

The 2026-09-30 entry's advice still stands and is still the right order:
this file only becomes tractable when the individual gaps are fixed on their
own merits — `operator.py`'s `partial`/lambda lowering first, which the entry
measures as the largest bucket (~19 sites). It is not a single-cause fix and
should not be attempted as one.

## Status (2026-09-30 — rewritten; not an import-qualifier bug, not attempted)

The title is STALE, and for the same reason as its `Lib/contextlib`
sibling: the `request for member '__module__'` error it is named after
stopped being this file's blocker (its own 2026-08-06 entry says so). What
the file actually hits is a GRAB BAG of unrelated compile gaps, and every
one of the ~10 accumulated "re-verified unchanged" entries below was
re-deriving the same bucketed error census rather than narrowing anything:
`operator.py`'s `partial`/lambda lowering, the posixpath/ntpath
struct-shape mismatch, `enum.py`'s struct/dict `%`, and the bare-name
collision class behind "task #141". None of those is an
import-qualifier, decorator or symbol-resolution problem, and this doc is
filed under `construct:decorators-and-import-qualifiers`, so the
accumulated history is deleted rather than extended: a `bugs/` entry a
reader has to page through ten times to find the one open item is worse
than one that names it.

**This session's import-qualifier work was checked against this file's
shape and did not change it**: the re-export-hop resolution
(`_find_symbol_home_module`) and the aliased-struct-construction fix are
verified by byte-identical generated C on a stdlib dylib unit
(`std/collections/_swisstable.mojo`) and by `test_gimple.py` 333/333, not
by this file building.

**Next step**: this file only becomes tractable when the individual
gaps above are fixed on their own merits — `operator.py`'s
`partial`/lambda lowering first (it accounts for the largest bucket, ~19
sites). It is not a single-cause fix and should not be attempted as one.
