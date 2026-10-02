# FORMAL: the dotted-CALLEE spine exemption hides an unpublished name, so `os.environ.get(...)` is reported as a NUMBER compared with a string

**Area:** FORMAL (`formal/build.py`, `check_module_symbols`). **Status: OPEN —
filed with the measurement that says what the fix may not be. NOT FIXED HERE
because the narrowing that sounds right is measurably wrong (below), and the
one that is right is a change to how a dotted callee's spine is resolved, which
is this tree's most-used import shape (`os.path.*` everywhere) and cannot be
verified from a light worker.**

Found by the arm64 formal sweep of the repo's own `a`–`f` files (slice
`repo-a`), where it is the terminal cause reported for `determinism_trace.py`.

## What I ran

```
$ python3 tools/formal_sweep.py -j 2 -t 300 determinism_trace.py --no-stdlib
CODEGEN: determinism_trace.py  (build: `_v == '1'` compares a NUMBER with a
  string, and the string comparison this would lower to is `strcmp`, which
  DEREFERENCES both operands … Ask one of the two questions instead — the
  byte's value, `_v == 46` … or the string's content, `str_at('1', 0, ".")` …)
```

and the five-line reproducer, which is the whole bug in isolation
(`.tmp/env_probe.py`):

```python
import os


def probe(k):
    v = os.environ.get(k, '')
    return v == '1'
```

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/a.out .tmp/env_probe.py
build: `v == '1'` compares a NUMBER with a string, …
```

## What I expect

The build to say what is actually wrong with the line, which is that the formal
`os` publishes no `environ`:

```
$ cat .tmp/p_a.py                     # return os.environ      (not a call)
$ python3 fire.py build --formal --no-prove --backend=arm64 …
build: probe: os.environ reads 'environ' out of the imported module `os`, and a
  module is not a value this path can place … What `os` publishes: chdir, chmod,
  curdir, devnull, extsep, getcwd, getenv, getenv_or, …
```

That sentence is the right one. Adding `.get(k, '')` and `== '1'` to the same
program turns it into a message about `strcmp` and about writing `'1'` as the
number 46 — which is advice for a `Pointer[UInt8]` subscript, sent to a reader
whose line is an environment lookup. **A refusal that names a construct the
file does not contain is worse than no refusal**: it sends the reader to look
for a byte comparison in an `os.environ.get`.

## The cause: the exemption is unconditional, and `os.path` shows why it cannot be made conditional on the export table

`check_module_symbols` collects every `MemberExpr` that reads an attribute of
an imported module and refuses it with `model.module_attribute_refusal`. It
skips any link on a CALL's dotted spine, and the comment there gives the
reason — "a CALL through the chain is the callee exemption's business … Every
link on the callee's spine is skipped, `os.path` included".

That is right for `os.path.join("a", "b")`, which resolves, and wrong for
`os.environ.get(k, '')`, which does not: nothing publishes `environ`, so the
call cannot bind a symbol, and the check that would have said so never asks.
What fires instead is much further downstream:

```
$ cat .tmp/p_d.py                     # v = os.environ.get(k); return v
$ python3 fire.py build --formal --no-prove --backend=arm64 …
build: p_d.py: the image would bind 1 symbol(s) that nothing provides, so it
  could not be loaded: os.environ.get. …
```

and with a comparison after the binding, the string comparison — which is
raised during EMISSION, later than the link-time symbol check — wins the race
and becomes the file's verdict.

**The narrowing that sounds right is measurably wrong, and this is the
measurement.** "Exempt a spine link only if the module publishes it" refuses
`os.path.join`. `os` publishes 28 names and `path` is NOT one of them:

```
$ python3 -c "… spy on formal.build._module_published_names …
                compile_formal('.tmp/p_a.py') …"
    os -> ['chdir', 'chmod', 'curdir', 'devnull', 'extsep', 'getcwd', 'getenv',
           'getenv_or', 'linesep', 'listdir', 'listdir_free', 'listdir_get',
           'listdir_len', 'makedirs', 'mkdir', 'os_free', 'pardir', 'pathsep',
           'putenv', 'remove', 'rename', 'replace', 'rmdir', 'sep']  n=28
```

`os.path` is a SUBMODULE with its own library (`formal/hostmods/os/path/`), so
it resolves through `model.dylib_export_tables`' module table and not through
`os`'s export table at all. And `_module_published_names` is not even consulted
for `os.path.join` today — the spine exemption short-circuits before the lookup
— so the discriminator a fix needs is not "published" but "is a module with a
library on this link line".

## The next step, in the order it should be done

1. **Decide the discriminator and put it in one place.** A spine link is exempt
   when it resolves — as an exported name of the module OR as a submodule that
   has a dylib on `link_line` — and is refused when it is neither. Both halves
   are already computed during a build (`M.dylib_export_tables` gives the
   per-module export sets and the set of modules with libraries), so this is a
   question with a table behind it rather than a new rule. It must be ONE
   predicate, asked from both the member walk and whatever the callee
   exemption uses, or the two will disagree the way this pair already does.
2. **Then make the refusal WIN where it already exists.** With (1) in place,
   `os.environ.get(...)` is in `module_reads`, which `check_module_symbols`
   raises at the END of its own walk — before any emission — so it beats the
   string comparison on its own. No ordering change is needed for this case,
   and adding one would be the wrong shape: it would be a special case for
   `os.environ` rather than the general rule.
3. **Verify with `compile_stdlib.py`, which is the only measurement that
   covers the risk.** `os.path.*` is used by a large share of the 664 stdlib
   modules and NONE of them is a candidate for a new refusal. A change here
   that is right in principle and refuses `os.path.join` shows up as a jump in
   `FAILED: N (E expected, U unexpected)`, so `U` not increasing is the
   acceptance criterion — the same one `formal/hostmods/os/__init__.mojo`'s own
   module note argues for when it refuses to spell `mkdir(path, mode)` with a
   default. **That check is the integrator's, not a light worker's.**

## What is deliberately NOT claimed here

* This unblocks no file. `determinism_trace.py` is refused either way; the
  refusal is just about the right thing afterwards, which is the same
  "diagnostic-accuracy, not coverage" class as
  `bugs/FORMAL_mlir_refusal_preemption.md`.
* `os.environ` being absent from the formal `os` is a TRUE limit and stays
  refused. `formal/hostmods/os/__init__.mojo` says so in its own module note:
  "`environ` IS ITS THREE FUNCTIONS … `getenv`, `putenv` and `unsetenv` are the
  whole of what can be reached, and they are what `os.environ.get(k)` and
  `os.environ[k]` have to become." Closing that half is a separate capability
  question (a `char **` walk, or a source rewrite to `os.getenv_or` in the
  importer) and this doc is not proposing it.

## Note on the sweep's own accounting

The sweep files this verdict as `codegen` for `determinism_trace.py`, because
the refusal is in the file. That classification stays right — the construct is
in the file, the file cannot build — but the line a reader sees names a
construct the file does not contain, which is what §"What I expect" is about.