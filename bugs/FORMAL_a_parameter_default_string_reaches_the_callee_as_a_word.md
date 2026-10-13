# FORMAL_a_parameter_default_string_reaches_the_callee_as_a_word: an
# UNANNOTATED parameter whose only value comes from its default is typed from
# the CALL SITES and they never mention it, so a string default is a number

**Area:** the formal parameter-kind evidence — `formal/model.py`'s
`ValueKinds`'s `param_kind` hook, which is `parameter_kinds_by_call_site` — and
the two consequences measured below. Both backends. **Status: OPEN, not fixed;
filed while working through `bugs/FORMAL_*` on `work/formal335-docs`, where it
was hit as a wrong answer rather than looked for.** It is not in any of the
eight docs that worker claimed and it is against no live claim.

## What I ran, and what I saw

The whole program, `fire.py build --formal --no-prove` then RUN, both
architectures, against CPython:

```console
$ cat .tmp/db.mojo
def f(x="plain"):
    return x

def main():
    print(f())

$ python3 .tmp/db.py          # the same text as a Python script
plain

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/db.bin --backend=arm64 -n 3 .tmp/db.mojo && .tmp/db.bin
4295461054                    # arm64;  4373731552 on x86_64
```

**A pointer, printed as a decimal number, where the source says `plain`.** The
build exits 0 both times, so this is the wrong-but-exit-0 shape rather than a
refusal.

The controls say which half is at fault, and it is the DEFAULT and not the
string parameter or the string value:

| program | CPython | arm64 / x86_64 |
|---|---|---|
| `def f(x="plain"): return x`; `print(f())` | `plain` | **pointer** / **pointer** |
| `def f(x="plain"): return x`; `print(f("plain"))` | `plain` | `plain` / `plain` |
| `def f(x=7): return x`; `print(f())` | `7` | `7` / `7` |
| `x = "plain"; print(x)` | `plain` | `plain` / `plain` |

**And the callee refuses the same value when the body uses it as a string**,
which is the second, load-bearing symptom: the parameter is not merely
mis-printed, it is a WORD for the whole body:

```console
$ cat .tmp/db2.mojo
def f(x="plain"):
    if x == "plain":
        return 1
    return 0

def main():
    print(f())

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/db2.bin --backend=arm64 -n 3 .tmp/db2.mojo
build: `x == 'plain'` compares a NUMBER with a string … it would be handed the
value of `x` as an address …
```

`len(x)` in the same position is refused the same way. An explicit argument at
the call site makes both lower correctly, and that is the whole of the cause.

## Why

`ValueKinds`'s `param_kind` is `parameter_kinds_by_call_site`, and its own
docstring states the rule: an UNANNOTATED parameter's kind is the unanimity of
the shapes the CALL SITES hand it, and "a call site that says NOTHING is one of
the claims". `def f(x="plain")` has exactly one call site, `f()`, and it passes
nothing — so the argument list contributes no shape, the parameter gets no
`STR_KIND`, and `formal/model.py`'s default for a word is "an integer" (see
`ValueKinds`'s "a parameter's annotation is the only thing that says what an
unassigned name holds; without one it is a word, so an integer").

**The evidence the table is missing is the callee's OWN default.** A
`def f(x="plain")` is a declaration that says `x` is a string as plainly as
`def f(x: String)` does; `param_defaults["x"]` is the `StringLiteral` node, and
`_parameter_argument_shape` already knows how to classify exactly that node when
it arrives from a caller. The default is substituted into the call's slot by
`bind_call_arguments`/`_fill_gaps` at emission time — *after* the kind table has
been built — so the emitter materializes a `char *` into a slot the callee was
told holds a number.

## The exact next step

1. **Count a parameter's own default as a claim on its kind, in
   `parameter_kinds_by_call_site`.** For every function in `functions`, for every
   `(pname, expr)` in `fn.param_defaults` whose `pname` is one of the function's
   positional parameters, add `_parameter_argument_shape(expr)` to that
   parameter's claim set exactly the way a call-site argument is added today.
   The unanimity rule then does the rest: a default that disagrees with a call
   site still claims nothing, and a parameter with neither an annotation, a
   default nor a readable call site is untouched.
2. **Re-measure the four rows above** (`test_formal_run.py`'s both-arch runner is
   the natural home, and `def f(x="plain")` / `def f(x=7)` are the pair — an
   unannotated defaulted INT parameter must keep answering as it does today, so
   the fix must not make `7` a string).
3. **Check `parameter_kinds_by_call_site`'s other consumers for a moved
   verdict.** It feeds `ValueKinds.param_kind`, which is read by
   `truthy_lowering`, `len`, the container row and the string-kind table, so a
   parameter that gains `STR_KIND` from its default gains every lowering that key
   gates. `test_formal_run.py` (1209 checks, which already carries the
   unannotated-parameter rows
   `both_arch_len_of_an_unannotated_parameter_every_call_site_passes_a_list` and
   `len_of_a_list_parameter_needs_every_site_to_agree`) and
   `test_formal_container_methods.py` are the narrow sets.

**What NOT to do:** teach the emitter to look at the default node at the call
site. The callee's parameter kind is a property of the DECLARATION and is asked
while the CALLEE is being lowered, where the call sites are not in hand; a
per-call-site fix would answer differently in the callee and in the caller, which
is the shape every table in this area exists to prevent.

## Related, found by the same probe, and a SEPARATE root cause (do not fix it in this doc's change)

**An f-string literal written as a parameter default is not caught by
`formal/model.py::refuse_interpolated_literals` either.** A default expression
hangs off `FunctionDef.param_defaults`, which is a DICT, and `iter_nodes` descends
into `list`/`tuple` but not into a dict — so the whole-default walk skips it and
the refusal never fires:

```console
$ cat .tmp/fh.mojo
def f(x=f"n={5}"):
    return x

def main():
    print(f())

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/fh.bin --backend=arm64 -n 3 .tmp/fh.mojo && .tmp/fh.bin
4365846718                    # a pointer; CPython prints n=5
```

That is 0 corpus files (a grep for `= f"` in a parameter list finds none in this
repository or the stdlib), so it is worth knowing about rather than urgent — and
its fix is the walker question (`iter_nodes` reaching a dict's VALUES, the way
`formal/build.py::_fold_target_queries_in` already does for `param_defaults` on
purpose), which is a shared-walker change with a wider blast radius than this
doc's one table and is deliberately NOT bundled here.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ printf 'def f(x="plain"):\n    return x\n\ndef main():\n    print(f())\n' > .tmp/db.mojo
$ for A in arm64 x86_64; do
    python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/db.$A --backend=$A -n 3 .tmp/db.mojo && .tmp/db.$A
  done        # two pointers; CPython's `python3 .tmp/db.py` prints `plain`

$ printf 'def f(x="plain"):\n    if x == "plain":\n        return 1\n    return 0\n\ndef main():\n    print(f())\n' > .tmp/db2.mojo
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/db2.bin --backend=arm64 -n 3 .tmp/db2.mojo
  # build: `x == 'plain'` compares a NUMBER with a string …
```
