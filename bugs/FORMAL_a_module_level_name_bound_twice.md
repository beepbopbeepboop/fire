# Two more module-level names are bound twice, and one of them has two live answers

**Area:** `formal/build.py`, `formal/imports.py`. **Status: OPEN, not fixed —
both are other lanes' files.** Found 2026-10-03 on `work/formal13-5` while fixing
`bugs/FORMAL_nullable_pointer_aliases_is_defined_twice.md` (deleted: it is the
same defect class in `formal/model.py`, and the two instances there are gone).

The class: a module-level name assigned twice. Python rebinds, so the first
definition is dead, every reader gets the second, and a reader who edits the
first gets a green run and no behaviour change. `formal/model.py` had two
(`NULLABLE_POINTER_ALIASES`, `function_value_refusal`); these are the other two,
found by the same `ast` walk that is now a test
(`test_formal_external_call.py`'s `no_module_level_name_is_bound_twice`, which
reads `formal/model.py` only and says so).

```console
$ python3 -c "
import sys; sys.path.insert(0,'.')
from test_formal_external_call import _module_level_names_bound_twice as f
for p in ('formal/build.py','formal/imports.py'): print(p, f(p))"
formal/build.py ['_expr_spelling (lines 2585, 2588)']
formal/imports.py ['HOST_MODULES (lines 665, 666)']
```

## 1. `formal/imports.py`: the first `HOST_MODULES` is dead, and it is a merge artifact

    665: HOST_MODULES = HOST_UNREACHABLE | HOST_MODELLED
    666: HOST_MODULES = HOST_UNREACHABLE | HOST_MODELLED | HOST_ADMITTED

Two adjacent lines, differing only by `| HOST_ADMITTED`, and the second wins. So
the live value includes `HOST_ADMITTED` and the first line does nothing — which
reads as "`HOST_ADMITTED` is deliberately outside the set", the opposite of what
the file says.

**Next step: delete line 665.** Nothing else in the file needs to move and no
answer changes: the binding that survives is the one every reader already gets.

## 2. `formal/build.py`: a dead alias over a SECOND implementation that disagrees with it

    2585: _expr_spelling = M.expr_spelling
    2588: def _expr_spelling(node) -> str:      # …a second, local one

The comment above 2585 is explicit about the intent — "`model.py` needs them for
its own refusals and a model function must not reach up into the build pass for
a string, so the model owns the one implementation and this file calls it" — and
the very next statement defines a second implementation, which shadows the alias
the comment is about. `formal/build.py` has ~15 `_expr_spelling(...)` call sites
(`formal/build.py:2605` onwards: `call_spelling`, the shadowed-global rows, the
`frame_len_refusal` argument, the name-placement walk) and they all call the
LOCAL one.

**This is not a harmless duplicate: the two spellings disagree, in both
directions, on 27% of the expressions in the corpus.** Measured by walking every
`IdentExpr`/`CallExpr`/`MemberExpr`/`BinaryOp`/`UnaryOp`/list/tuple/set/subscript
node of 100 `.mojo` files in this tree (14,238 nodes) and comparing
`build._expr_spelling(node)` with `model.expr_spelling(node)`:

| disagreement | count | example |
|---|---:|---|
| `model` answers `BinaryOp` (a type name, i.e. no answer) where `build` spells the operator | 3,700+ | `i + 1` vs `BinaryOp` |
| `model` omits the quotes on a string literal | | `'Sum:'` vs `Sum:` |
| `model` wraps a subscript's index in brackets where `build` does not | | `d[a]` vs `d['a']` |
| `model` spells a CALL whose callee is a member chain, where `build` falls through to the type name | | `os.path.splitext(os.path.basename(path))` vs `CallExpr` |

So `model.expr_spelling` is better at a member-callee call and worse at
operators and at quoting; `build._expr_spelling` is the reverse. Every refusal
that quotes a value goes through one of them, so a diagnostic's spelling
depends on which file raised it — and the two call sites that a reader would
compare (a `BinaryOp` in `formal/build.py`'s name-placement walk against the
same expression in `formal/model.py`'s refusal) print different text.

**Next step, in this order, because the merge is the fix and the alias makes it
one line:**

1. merge the arms into `formal/model.py`'s `expr_spelling` — take the union of
   the two (operator arms, quoted string literals, bracket-free subscripts,
   member-callee calls), so the model version is a superset;
2. delete `formal/build.py`'s local `def _expr_spelling` and leave the alias
   `_expr_spelling = M.expr_spelling` doing what its comment already says;
3. re-run whatever pins refusal TEXT, because step 1 changes it: a refusal that
   used to say `BinaryOp` will now say `i + 1`, which is the whole point and is
   also the reason this needs the suite that gates every commit rather than a
   narrow `test_formal_*.py`.

That is `formal/build.py`, which is under active edit by several formal lanes at
once, and step 3 is a gate this branch is not running — which is why it is
written down rather than done.