# CODEGEN: `_KNOWN_SIGS` still declares `py_tokenize` with TWO parameters, so `test_gimple.py` is red on master

**Found 2026-10-01 while merging the nine-branch bug batch into
`work/merge-bugs-batch`, running the narrow test files that batch touched.**
This is **pre-existing on master** and is not an interaction between the
merged branches — it is listed here because it is one of the two red cases in
`python3 test_gimple.py` on the merged tree and a merge report that did not
name it would be a merge report that hid one.

## What I ran and what I saw

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_gimple.py
    ...
    FAIL  handwritten_selfhost_signature_tables_match_the_source:
      py_tokenize: table declares 2 C parameter(s), the source takes 1 (['src'])
      — a DEFAULTED parameter still occupies a C parameter slot
    Results: 351 passed, 1 failed

The check derives each arity from the **real function object** with
`inspect.signature`, precisely so a hand-written table cannot drift
(`test_gimple.py`'s own docstring: "A hand-written table the compiler cannot
check is a table that will drift again"). Two copies disagree:

| copy | says |
|---|---|
| `gimple_codegen.py:3125` `_KNOWN_SIGS['py_tokenize']` | `('MojoList *', ['char *', 'char *'])` |
| `fire_compiler.py:1515` `def py_tokenize(src: str)` | one parameter |
| `runtime/fire_runtime.h` | `MojoList *py_tokenize(char *source)` — one parameter |

## Expected

All three copies say ONE parameter, and the check passes.

## What is actually there: THREE copies, and the two hand-written ones agree with each other and disagree with the source

| copy | says |
|---|---|
| `gimple_codegen.py:3125` `_KNOWN_SIGS['py_tokenize']` | `('MojoList *', ['char *', 'char *'])` — **two** |
| `runtime/fire_runtime.h:1816` | `MojoList *py_tokenize(char *source, char *filename);` — **two** |
| `fire_compiler.py:1515` `def py_tokenize(src: str)` | **one** |

That the header agrees with the table is why only ONE problem line is printed:
the check's header arm (`test_gimple.py:7759`) compares the header against
`_KNOWN_SIGS`, and the two are consistent with each other. It is the
`inspect.signature` arm — the one that compares a hand-written fact against the
**source** — that fires. Two hand-written copies agreeing is not evidence; it
is the failure mode this check exists for, one level down.

There is a third stale thing in the same comment block, `fire_runtime.h:1810`,
and it is the copy that will mislead whoever reads the header next:

```c
/* `py_tokenize`'s arity must match fire_compiler.py's definition
 * (`py_tokenize(src: str, filename: str = "")`) or every --dump-full
 ...
```

It quotes a source signature that no longer exists. A stale comment in the
header that tells the reader which source line to match is worse than no
comment, because it is checkable-looking.

## Why it is a half-finished fix rather than a new bug

`7ce61398` ("lexer: `py_tokenize` keeps its one-argument ABI; the filename
variant gets a name") fixed this exact drift. `fd10fd92` had given
`py_tokenize` a **defaulted** second parameter `filename`, used only to prefix
the unterminated-string diagnostic; `7ce61398` split that into an ordinary
`py_tokenize_named(src, filename)` and went back to `py_tokenize(src)`
delegating to it. Its own message describes the other copies as already
carrying one parameter —

> `py_tokenize` is a pinned C ABI symbol — in `GimpleGen._NO_OVERLOAD_MANGLE`,
> declared in `runtime/fire_runtime.h` as `MojoList *py_tokenize(char *source)`,
> and in `_KNOWN_SIGS` with that one parameter

— and that is exactly the shape they should have been left in. What it fixed
was the **source**, which is enough to make the self-host codegen emit
one-argument calls, and it measured whole-closure codegen +
`gcc -fgimple -fsyntax-only` at 0 errors, from 61. It did not walk back the two
hand-written copies, so they now describe a function that has not existed since
that commit.

Verified that the residue is on master itself and not something this merge
introduced:

    $ git show master:gimple_codegen.py | grep "'py_tokenize':  "
        'py_tokenize':              ('MojoList *', ['char *', 'char *']),
    $ git show master:fire_compiler.py | grep 'def py_tokenize'
    def py_tokenize(src: str) -> list[Token]:

So `test_gimple.py` is gate-red on master for this, and it is very likely part
of what `master-selfhost-fix2` is already chasing ("master's self-host build is
red"). **Do not fix it twice:** if that branch changes these lines, this doc is
what should be deleted.

## Exact next step

Two lines and one comment, and the three must move together — that is the whole
reason this is filed as a bug rather than a nit:

1. `gimple_codegen.py:3125` `_KNOWN_SIGS`:

       -        'py_tokenize':              ('MojoList *', ['char *', 'char *']),
       +        'py_tokenize':              ('MojoList *', ['char *']),

2. `runtime/fire_runtime.h:1816`:

       -MojoList *py_tokenize(char *source, char *filename);
       +MojoList *py_tokenize(char *source);

   and `fire_runtime.h:1810`'s comment, which currently quotes
   `py_tokenize(src: str, filename: str = "")`: name
   `py_tokenize(src: str)` and say that the filename-carrying variant is
   `py_tokenize_named(src, filename)`, whose arity the codegen derives from its
   definition like any other function's — which is why it needs no entry in
   either hand-written copy.

Then confirm the two things a green `test_gimple.py` does **not** cover,
because that check only proves the copies agree with the source and with each
other:

1. `python3 test_gimple.py` — the check goes green and **stays** green.
2. `python3 test_string_literal_lexing.py` — 75/75, i.e. the two callers that
   want a filename (`fire.py`'s `_parse_arm64_module`, `formal/build.py`'s
   `parse_module`) still get their `file:line:col:` prefix. That behaviour now
   lives in `py_tokenize_named`, so a mistake in step 2 that dropped the
   second parameter from the header while leaving the source alone would make
   the self-host link against a two-parameter prototype for a one-parameter
   definition — `conflicting types`, which is the error `7ce61398` was written
   to remove.

Because `gimple_codegen.py` and the runtime header are both compiled-path
files, CLAUDE.md requires a full `make gate` for this, and the merge worker that
found it is not permitted to run one. The integrator's gate over the batch will
cover it.