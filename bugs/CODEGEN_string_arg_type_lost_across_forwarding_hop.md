# CODEGEN: a string argument's type is lost across a forwarding hop, so the callee prints the pointer's digits

Found 2026-10-01 while measuring
`bugs/COMPILE_FAIL_Tools_unicode_gencodec.md` — its "header line prints
pointer digits" divergence is this, and this is the reduced form of it.

## The repro

```python
def sink(x, y, z):
    return '%s and %s' % (x, y)

def mid(a, b):
    return sink(a, b, None)

def go():
    return mid('readme', 'b')

print(go())
```

| | output |
|---|---|
| `python3` | `readme and b` |
| `python3 fire.py run` | `readme and b` |
| `python3 fire.py build` + run | `4343976656 and 4343976664` — **exit 0** |

`sink`'s own params are declared `int64_t`, so `'%s'` formats the boxed
`char *` as a decimal address. In the generated C:

```c
char * sink_37bd8e (int64_t, int64_t, int64_t);   /* ← wrong */
char * mid_1b532c  (char *, char *);              /* ← right */
```

**This is a silent wrong answer, not a refusal** — exit 0, no
diagnostic, a plausible-looking number where a name belongs.

## Reduced to the essential shape

Both halves are needed; remove either and it works:

- **Call the callee directly** with a string (or even a string local):
  `sink('a','b',None)` → `a and b`; `sink(n,'b',None)` where
  `n = 'readme'` → `readme and b`. Correct.
- **Pass literals one level up** — `mid('readme', 'b')` — still wrong,
  because the loss is at the *forwarding* call inside `mid`, not at
  `go`'s call.

So the trigger is: **an unannotated callee parameter that is only ever
passed a caller's own unannotated parameter.** `sink`'s `x`/`y` have no
body-usage signal (`'%s' % (x, y)` is a container-shaped format, not a
string op) and their one call site passes `mid`'s params, which are
themselves unresolved at observation time.

## Root cause, traced

`_arg_scalar_type`'s own docstring already names this exact limitation,
and explains why it is not simply switched on:

> `prefer_refined_param` lets a REFINED cross-call scalar contract for the
> caller's own parameter outrank a possibly-stale `_inferred_var_types`
> entry … **Scoped to the method pass** because its observations land ONLY
> on method parameters; giving the free-function pass the same precedence
> changed what Pass 1.3d observed about FREE callees (real instance:
> `ntpath.split` refined to char* from forwarded arguments while its own
> forwarders `basename`/`dirname` stayed int64_t-typed — new
> `-Wint-conversion` errors at those forwards), and a free function's full
> caller set is not visible to any fixpoint here, so such a flip cannot be
> made consistent.

Measured on this repro, and it is worse than "stale precedence" — it is
**ordering**. The free-function scalar-observation collection loop
(`module_gen.py`, the `for caller_name, body in _caller_bodies:` loop
that populates `_scalar_obs`) runs with `_inferred_param_types` still
empty for every function:

```
# at the first `sink(...)` call site seen by _calls_in_stmts:
ivt={'sink': {}, 'mid': {}, 'go': {}}
ipt={'sink': {}, 'mid': {}, 'go': {}}
```

`mid`'s `char *` is established LATER, by the free-function contract's own
apply loop (`for callee in sorted(_scalar_obs):` …) and by
`_gmi_apply_call_site_param_evidence`. So by the time `mid` is known to be
`char *`, the observation of `sink(a, b, …)` has already been made and
recorded as "no evidence", and nothing re-runs.

Two independent confirmations that this is the whole story:

- Passing `prefer_refined_param=True` at the collection site
  (`_arg_scalar_type(caller_name, a, False, True, None)`) changes
  **nothing** — verified by patching exactly that line and re-generating.
  The flag reads `_inferred_param_types`, which is empty at that moment,
  so both branches of its `if` fall through identically.
- `_gmi_apply_call_site_param_evidence` (the other pass that refines from
  call sites) documents itself as deliberately narrow and cannot help
  here: it records only **literal** arguments (`_gmi_literal_ctype`), and
  only resolves **str-vs-container** for containers
  (`containers = ('MojoList *', 'MojoSet *', 'MojoDict *')`) — a string
  argument is not a container, so `'readme'` is not even in its evidence
  set.

So the missing piece is a **fixpoint**: re-run the free-function scalar
observation after the apply loop, so a chain `go → mid → sink` settles.
The docstring's warning is about a *single* flip without a fixpoint, which
is precisely why `ntpath.split`'s forwarders broke when it was tried. A
bounded fixpoint that requires unanimity and a final stable state is a
different proposition from what was reverted.

## Next step

Make the free-function scalar contract iterate: collect → apply →
re-collect → apply, until neither changes (mirroring
`_apply_method_scalar_obs`'s existing `for _mse_round in range(4)` loop,
which is already a bounded fixpoint for the method half). Bound it, and
require unanimity at every round as the pass already does, so a chain
that cannot settle stops changing rather than oscillating. The
`ntpath.split` regression to avoid re-introducing is specifically a
*forwarder* being re-typed from a callee's refinement — worth an explicit
regression case when that is attempted, not just the repro above.

A regression test belongs beside `test_gimple.py`'s
`test_scalar_arity_min_max_params_are_not_containers` (same shape: one
program, both pipelines, asserted against CPython's stdout rather than a
literal, since the fix changes only a type and any value change would be
the bug).

## Where it shows up in the wild

`Tools/unicode/gencodec.py`'s generated `readme.py` opens with

```
""" Python Character Mapping Codec readme generated from '4385725232' with gencodec.py.
```

where CPython writes `run/readme.md`. The chain is
`convertdir` → `pymap(name, map, pyfile, encodingname, comments)` →
`codegen(name, map, encodingname, comments)`, whose first statement is
`'... Codec %s generated from '%s' with gencodec.py.' % (encodingname,
name, ...)`. See
`bugs/COMPILE_FAIL_Tools_unicode_gencodec.md`'s re-scoped item 1, which
records the symptom and previously attributed it to
`os.path.join(...)`-shaped call-site evidence being invisible; this is the
mechanism behind it.