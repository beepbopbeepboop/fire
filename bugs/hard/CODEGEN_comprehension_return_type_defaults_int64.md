# HARD BUG: a function/method whose sole `return` is a bare list/dict/set comprehension gets its inferred return type wrongly defaulted to `int64_t`

## Status

Unfixed. Root-caused 2026-08-06 while classifying the `CODEGEN_generator_
function_Lib_*.md` cluster (tasks #95-135) — found via `Lib/calendar.py`,
whose own `Calendar.monthdatescalendar` (and 5 sibling methods) hit this
directly. Confirmed live on current master (`2b0c4c5`). Not attempted:
`_quick_type` is a large (~250-line), heavily-relied-upon, project-wide
expression-type estimator used throughout return-type inference,
call-argument coercion, and more — the exact class of "shared inference
machinery" this session's standing guidance says to touch only with a
dedicated, carefully-verified pass, not as a drive-by fix bundled into
cluster classification work.

## Why this belongs in this cluster (even though it isn't a coroutine bug)

Filed alongside the `CODEGEN_generator_function_Lib_*` cluster because
that's exactly where it was found and because it's the dominant reason
several of those files currently fail — but it is important to note
explicitly: **this is NOT a bug in the C++20-coroutine generator codegen
path** (`_gen_cpp_generator_unit` et al.). It's a bug in `_quick_type`,
the ordinary/general-purpose plain-C `.ci` (GIMPLE) return-type inference
used for EVERY function in the program. It surfaces disproportionately
often in this generator-codegen cluster's files because those files'
authors habitually write the idiom "consume a generator into a list via
`list(self.some_generator(...))`, then `return [transform(x) for x in
that_list]`" — i.e. the generator-consuming caller (not the generator
itself) is what trips this bug.

## Symptom

```
$ python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/calendar.py
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: non-trivial conversion in 'integer_cst'
/Users/mrs/net/Python-3.14.6/Lib/calendar.py:281:1: error: type mismatch in binary expression
```//repeated at :291, :299, :309, :319, :328, once per subclass that
inherits the affected method (7 classes total in calendar.py alone, so
this one root cause produces 7x2=14 distinct GCC errors from one bug).

## Root cause

`GimpleGen._quick_type(self, node)` (`gimple_codegen.py`) is the
syntactic, no-emission expression-type estimator used by
`_collect_return_types`/`_infer_return_type` (which populates
`func_return_types` for every unannotated function/method, Pass 2/2b of
`gen_module`) and by several other inference passes. It has explicit
`isinstance` branches for `IntLiteral`, `FloatLiteral`, `BoolLiteral`,
`StringLiteral`, `IdentExpr`, `BinaryOp`, `CompareChain`, `UnaryOp`,
`TernaryExpr`, `CallExpr` (both `IdentExpr` and `MemberExpr` callees),
`MemberExpr`, `ListExpr`, `DictExpr`, `SetExpr`, `TupleExpr`,
`SliceExpr`, `SubscriptExpr` — but **no case at all for `Comprehension`**
(`mojo_compiler.py`'s AST node for `[x for x in y]`/`{k: v for ...}`/
`{x for x in y}`/generator-expressions, distinct from the literal
`ListExpr`/`DictExpr`/`SetExpr` nodes, which ARE handled). Because
`Comprehension` matches none of the `isinstance` checks, control falls
through to the method's final line, `return 'int64_t'`.

`return [ dates[i:i+7] for i in range(0, len(dates), 7) ]` parses to a
`Comprehension(kind="list", ...)` node. `_collect_return_types` calls
`self._quick_type(node.value)` on it, gets `'int64_t'` back, and that
becomes the method's registered return type in `func_return_types` (and
therefore its forward declaration's return type in the emitted C).

The method's *body*, however, is lowered correctly at emission time by
the SEPARATE, more thorough `_lower_Comprehension` — which knows a list
comprehension really produces a `MojoList *` — so the generated C ends up
with a mismatch: a forward declaration promising `int64_t`, and a `return`
statement that actually constructs a `MojoList *`, then pointer-casts it
down to `int64_t` to satisfy the wrong declared type:

```c
int64_t __GIMPLE Calendar_monthdatescalendar (Calendar * self, int64_t year, int64_t month)
{
  ...
  MojoList * _t8;              /* the REAL comprehension result */
  ...
  _t19 = (void *)_t8;
  _t20 = (int64_t)_t19;        /* pointer-to-int cast to fit the WRONG decl */
  _t18 = _t20;
  return _t18;
}
```

`gcc -fgimple` correctly refuses this shape ("non-trivial conversion in
'integer_cst'" / "type mismatch in binary expression") — the intermediate
list-slicing loop inside the comprehension (`mojo_list_slice`,
`mojo_list_append_int`, `i < _t9` comparisons) mixes the real
`MojoList *`-typed temporaries with the `int64_t`-typed ones the wrong
declared return forces elsewhere, producing several distinct GIMPLE
verifier complaints from the one root cause per affected method.

## Why this wasn't caught by the routine `compile_stdlib.py`/dylib gates

`return <comprehension>` as literally the SOLE, entire return expression
of a function (not stored in a local first, not one of several
differently-shaped return paths) is common but not universal — many
real-world comprehension-returning functions in the wider stdlib corpus
assign to a local first (`result = [x for x in y]; return result`, where
`_quick_type` on the local's own IdentExpr resolves through
`self.var_types`, which — populated by the ACTUAL, correct emission-time
lowering by the time a later statement references it — masks the bug for
that shape) or have multiple return paths that also include a
differently-typed non-comprehension branch. The specific "bare `return
[comprehension]`, nothing else" shape is what calendar.py's six sibling
methods all hit identically, which is likely why it surfaced so
consistently there but plausibly not everywhere a comprehension appears
in a return position across the full 664-file corpus.

## Confirmed occurrences

- `Lib/calendar.py`: `Calendar.monthdatescalendar`, `monthdays2calendar`,
  `monthdayscalendar`, `yeardatescalendar`, `yeardays2calendar`,
  `yeardayscalendar` (and every subclass that inherits them — 7 classes
  total) — see `bugs/CODEGEN_generator_function_Lib_calendar.md`.

Not yet independently confirmed in a second file with a full trace (a
few OTHER errors seen in this session's broader build logs — e.g.
`Lib/functools.py:920`'s `_is_valid_dispatch_type`, whose sole return is
`isinstance(...) and all(isinstance(arg, type) for arg in
cls.__args__)` — are a RELATED but distinct trigger: `_quick_type` has no
`CallExpr` case for the builtins `isinstance`/`all`/`any` either, so
those also silently default to `int64_t` where the real value is
`_Bool`. Same missing-case root cause in the same method, different AST
node shape; left as a related-but-unconfirmed data point rather than
folded into this doc's "confirmed occurrences" list, since it wasn't one
of this cluster's 41 target files and wasn't independently traced end to
end the way calendar.py was.)

## What a fix needs

Add a `Comprehension` case to `_quick_type` that estimates
`'MojoList *'`/`'MojoDict *'`/`'MojoSet *'` per `node.kind`, mirroring
the existing `ListExpr`/`DictExpr`/`SetExpr` literal cases. This alone is
a small, mechanical addition — but per this project's own "narrow scope"
discipline, it should be scoped/tested carefully: `_quick_type` is
consulted from many call sites beyond just return-type inference (call-
argument coercion, container-element-type pre-passes, etc. — grep shows
dozens of call sites throughout `gimple_codegen.py`), so changing its
behavior for ANY node shape is exactly the kind of "shared inference
machinery" change that has previously caused confident-looking
regressions elsewhere in this codebase (see this session's own guidance
citing the `_tuplegetter`/unannotated-`__init__`-param investigations).
A real fix should re-run the FULL 5-step quality gate (test_gimple.py,
test_module_cache.py, make check-selfhost, from-scratch stdlib dylib
rebuild comparing skip count, compile_stdlib.py -j8 comparing 664/664),
not just the two fast unit-test suites, exactly as CLAUDE.md's own
codegen quality-gate section already mandates for any `gimple_codegen.py`
change.

## Minimal repro

```python
class Widget:
    def make_rows(self, n):
        items = [i for i in range(n)]
        return [items[i:i+2] for i in range(0, len(items), 2)]

def main():
    w = Widget()
    print(w.make_rows(6))

main()
```
Expected (per root cause above): `Widget_make_rows` gets forward-declared
`int64_t` while its body constructs and returns a real `MojoList *`,
producing the same "non-trivial conversion"/"type mismatch" `-fgimple`
errors as the real `calendar.py` case.
