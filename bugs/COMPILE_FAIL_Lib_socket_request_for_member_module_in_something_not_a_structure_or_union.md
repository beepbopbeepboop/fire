# COMPILE_FAIL: Lib/socket.py — an unrelated grab-bag of compile gaps (title STALE)

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

`Lib/enum.py:380` is itself a `for`-target/`self._member_names` list-length
read on an `int64_t`-typed receiver — the boxed-value class. It is the same
shape as `bugs/CODEGEN_unannotated_dict_param_value_type_not_propagated.md`
(newly filed this session: a value whose real C type is known at the binding
site but not at the use site), one indirection further in.

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
