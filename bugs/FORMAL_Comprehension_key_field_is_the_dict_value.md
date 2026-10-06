# `fire_compiler.Comprehension`'s `key` field holds the dict's VALUE, and two comments say it is the key

**Area:** FORMAL / the parser. `fire_compiler.py`'s
`Comprehension` dataclass and `_parse_dict_or_set`, read by `formal/model.py`'s
`ValueKinds.kind_of`. **Status: NOT FIXED — it is in `fire_compiler.py`, which
owes a full `make gate`, and this branch's worker is not permitted to run one.**
The one behaviour this document measures is CORRECT; what is wrong is the
label, and the label has already cost a reader.

## What was run

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 - <<'PY'
import sys, os; sys.path.insert(0, os.getcwd())
import fire_compiler as F
for src in ('x = {k: 1 for k in d}', 'x = [k for k in d]',
            'x = {k: v for k, v in d.items()}'):
    c = F.Parser(F.py_tokenize(src)).parse_module()[0].value
    print(src, '| kind=', getattr(c, 'kind', None),
          '| element=', c.element, '| key=', c.key)
PY
x = {k: 1 for k in d}    | kind= dict  | element= IdentExpr(name='k', line=1, col=5) | key= IntLiteral(value=1, line=1, col=8, raw='1')
x = [k for k in d]        | kind= list  | element= IdentExpr(name='k', line=1, col=5) | key= None
x = {k: v for k, v in d.items()} | kind= dict | element= IdentExpr(name='k', …) | key= IdentExpr(name='v', …)
```

So for a dict comprehension `element` is the part **BEFORE** the colon and `key`
is the part **after** it — the opposite of what both comments say.

## The two comments

`fire_compiler.py:565`:

```python
    element: object
    key: object = None     # dict key
```

and `formal/model.py`, in the arm that classifies a dict comprehension (fixed in
`e685f464`, which corrected the `formal/model.py` half and left this one):

> `# \`e.element\` is the dict comprehension's VALUE (\`e.key\` is the key)`

**The CODE in that arm reads `e.element`, which is the KEY, and classifying a
dict comprehension by its key is right** — so the arm was correct and only its
comment was wrong. The reason is structural rather than the parser's spelling:
`_emit_dict` lays a pair blob out as `[count][k0][v0][k1][v1]…`, so word 0 is a
key, a `for`-in over one yields keys at `M.PAIR_STRIDE`, and `len` reads the
count. A dict **LITERAL** is classified by its VALUES instead
(`formal/model.py::container_literal_elem_kind`) because its initializer states
both and the element a subscript leaves in hand is the value — so the two arms
answer two different questions and are both right.

## What it cost

An hour of the branch that fixed
`FORMAL_a_comprehension_target_over_a_string_keyed_dict_is_an_int.md`: the arm
was first read as a key/value MISCLASSIFICATION, which sent the search into
"which of `element` and `key` is the value" instead of "why is neither of them
being read at the comprehension's own scope". The answer to that question
(`_kind_of_simple` has no scope stack) was the fix.

## The next step

1. `fire_compiler.py:565`'s `# dict key` becomes `# dict VALUE` — or, better and
   cheaper to keep true, the field is RENAMED to `value`. **A rename is a wider
   change than a comment** (every reader in `formal/` and the codegen has to
   move with it, and CLAUDE.md makes `fire_compiler.py` a full-gate change
   either way), so it should be a deliberate decision rather than a drive-by.
2. Grep every other reader of `Comprehension.key`. **This document has NOT done
   that** — it measured the two comments it had a reason to read, and the
   remaining readers are unexamined. `formal/model.py`'s list arm carries
   `if e.key is not None: ek = _unify(ek, …)`, which is unreachable for both
   shapes the parser produces (a list comprehension has `key is None`, and a dict
   one returns from the dict arm above), so it is either dead code or a guard
   against a shape this parser does not emit yet. **Deciding which is the next
   step's job too.**
3. `python3 tools/suite.py gate` — `fire_compiler.py` is the shared parser/AST
   and CLAUDE.md's rule for it is a full gate, because `gimple_codegen.py`'s
   lowering is a separate implementation and a parser change is invisible to the
   interpreter suites.