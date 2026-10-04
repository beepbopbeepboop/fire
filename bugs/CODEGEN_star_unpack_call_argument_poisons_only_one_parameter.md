# A `*`-unpack call argument is mapped onto ONE parameter, so every LATER parameter's yield slot silently defaults to int64_t

## What was run

```python
def gen(a, b):
    yield b

def main():
    args = [1, 'hello']
    for v in gen(*args):
        print(v)
main()
```

compiled (`do_imports=False`), built with gcc -fgimple, run:

```
gcc rc 0
CPython:  'hello\n'
compiled: '0\n'
```

No diagnostic, exit 0, and the string comes out as the integer `0` — the
value a pointer's word is when the slot that should have held it was never
given a type. This is the same class
`CODEGEN_coro_yield_kind_unresolved_callsite` exists for, in
the direction that record says was left: a `None` hole is now a refusal, but
a parameter the scan never *looks at* is neither a hole nor a kind, so it
is invisible to both halves of the rule.

## Root cause

`mojo/middle/coro.py`'s `_scan_callsite_param_kinds._visit_call` maps
`node.args` onto the callee's parameters **by index**, with no notion of an
unpack:

```python
for i, a in enumerate(node.args):
    if i >= len(pinfo):
        break
    pname, pann = pinfo[i]
    if not _unannotated(pann):
        continue
    slot.setdefault(pname, set()).add(_argkind(a, cenv))
```

A `*expr` or `**expr` call argument is a `UnaryOp` (`fire_compiler.py`'s
`UnaryOp(op='*')` / `op='**'`) sitting in that same `args` list, so
`gen(*args)` records ONE observation — a `_argkind(UnaryOp)` hole — against
`pinfo[0]`, i.e. `a`. `b` is never visited at all.

Measured on the registries, same source:

| call | `_CALLSITE_PARAM_KINDS['gen']` | `_CALLSITE_PARAM_CONFLICTS['gen']` |
|---|---|---|
| `gen(*args)` | `None` (nothing resolved) | `{'a'}` |
| `gen(1, 'hello')` | `{'a': 'i', 'b': 'p'}` | — |

`a` being refused is *accidentally* right — a `*`-unpack really can supply
it — and `b` is neither resolved nor conflicted, so
`_ambiguous_yielded_params` (which reads only `_CALLSITE_PARAM_CONFLICTS`)
lets the generator through and the yield slot falls back to
`_KIND_TO_SLOT_CTYPE[None] == 'int64_t'`.

## The two halves, and why one line fixes neither

* A `*`-unpack at positional index `i` can supply parameters `i` through
  `len(positional) - 1`, so every one of those is a hole. It cannot supply a
  KEYWORD-ONLY parameter, which is where the current code over-refuses if
  the fix is written carelessly.
* A `**`-unpack can supply ANY parameter by name — positional-or-keyword and
  keyword-only alike — so every parameter not already bound by an explicit
  keyword at this call site is a hole. This is the case
  `Tools/c-analyzer/c_common/scriptutil.py`'s `iter_marks` is in, and it is
  also why `scriptutil` cannot be unblocked by fixing the mapping:
  `iter_marks(groups=groups, **mark_kwargs)` yields `mark`, so `mark` is a
  genuine hole and the generator is right to refuse. Today's refusal reaches
  the right verdict for the wrong reason (it charged `mark` for being
  parameter 0), which is worth fixing anyway because the reason is what the
  diagnostic prints.

## Next step

In `_visit_call`:

1. Compute the callee's positional-parameter count as
   `len(params) - len(getattr(fn, 'kwonly', []) or [])`.
2. Walk `node.args` by index as now, but on the first `UnaryOp` with
   `op == '*'` record a `None` hole for every UNANNOTATED positional
   parameter from that index to the end, and stop (the unpack swallows the
   rest of the call's positional arguments).
3. If any `UnaryOp` with `op == '**'` is present, record a `None` hole for
   every UNANNOTATED parameter — positional-or-keyword and keyword-only —
   that is not bound by an explicit entry in `node.kwargs`. Keep the
   explicit-keyword observations: they are real evidence for those params.

That makes both halves of `_ambiguous_slot_message`'s wording true at once
("they disagree, or one of them the static scan could not type at all").

**The cost is a refusal where there was previously a silent wrong answer, so
expect some currently-compiling generators to start refusing.** That is the
intended direction, but it means this is not a change to make blind: measure
`python3 test_gimple_generator_runner.py` and `python3 test_gimple.py`
before and after, and treat a new refusal as a case to check by hand rather
than as a regression to paper over. `bugs/hard/
CODEGEN_coro_yield_kind_unresolved_callsite.md` records the regression
history of this exact machinery.

Regression to add next to it: the program above, asserted against CPython
(it must FAIL with the current tree and either refuse or print `hello`
afterwards — `0` is the outcome that must not survive), plus
`gen(1, 'hello')` as the control that must keep working.
