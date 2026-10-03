# FORMAL_except_arm_is_never_emitted: a `try`'s handler is dropped, silently

**Area:** FORMAL (`formal/arm64_codegen.py::_emit_try:1916`,
`formal/x86_64_codegen.py::_emit_try:1868`, and — as a consequence —
`formal/model.py::_build_cfg`'s `TryStmt` arm).
**Status: OPEN, not fixed. Both halves are measured below on both
architectures; the exact next step is written, and the reason it is not
already done is that it overturns a test row somebody pinned deliberately.**

## The finding

`formal` has no exception unwinder, so both backends' `_emit_try` **skip the
handler arms outright**. Their own docstrings say so — arm64: *"Handlers are
skipped: formal has no unwinder, so there is no edge from a raise site to an
except arm"*; x86-64: *"The except arms are SKIPPED … `raise` itself exits the
process, so no handler is ever reachable"* — and `RaiseStmt` flushes the pending
finallys and then `exit(1)`s (`arm64_codegen.py:1628`, `x86_64_codegen.py:1447`).

That is a defensible design decision. What is not defensible is that it is
**silent**: a handler's body can contain stores, calls and side effects, and
nothing tells the writer that none of them are in the image.

```mojo
def probe(n: Int) -> Int:
    try:
        sink(n)
    except ValueError:
        printf("HANDLER RAN\n")
    printf("after\n")
    return 0

def main(n: Int) -> Int:
    return probe(n)
```

Built and run, arm64:

```
$ python3 fire.py build --formal --no-prove -o h1 h1.mojo
Built: h1  [arm64/macho]
$ ./h1
body x=10
after
exit 0
```

`HANDLER RAN` is not printed, and **nothing** — no refusal, no warning, no
stderr line — says the arm was dropped. The program is silently not the program
that was written. That is the failure class CLAUDE.md calls out by name: "a
wrong-but-exit-0 artifact that every other check is structurally blind to".

## What it costs `read_before_store`, which is where this was found

`formal/model.py`'s CFG does the OPPOSITE: it runs the handler bodies and treats
their exits as paths to the join after the `try`. So a store in a handler looks
like a store the analysis knows about, and the two halves disagree in the
false-positive direction:

```python
def probe(n):          # REFUSED, on both backends
    try:
        p = 1
    except ValueError:
        pass
    return p
```

```
build: probe: 'p' is read at line 6 before anything in this function stores
it, and CPython raises UnboundLocalError for that program (NameError at module
level). …
```

Both halves of that sentence are false. CPython runs this program (`p` is
stored by the body, and the handler is never entered), and the emitted image
would be correct — the two sources below differ only in the statements the
emitter drops, and the second builds and runs:

| source | build | answer |
|---|---|---|
| `try: p = 1 / except ValueError: pass / return p` | **REFUSED** | — |
| `p = 1; return p` | built | exit 1 (`main` returns `probe(n)`) |

So the check refuses a program whose image is right, for a reason that is about
the language rather than about this backend.

**It is pinned, and the pin is the reason this is filed rather than fixed.**
`test_formal_read_before_store.py`'s `one_handler_stores_refused` asserts the
refusal, with:

> A handler that stores nothing is a path to the join that stores nothing, and
> nothing in the graph says the handler will not run — so this refuses a program
> CPython runs, because the `try` body here does not raise. That is the
> conservative direction and it is pinned deliberately: a rule that assumed a
> handler is dead would report the far more common `except: pass` shape as a
> store, which is the wrong way round.

Every sentence of that is about the LANGUAGE, and the premise "nothing says the
handler will not run" is answered by the emitter: nothing CAN run it. The
"wrong way round" it was protecting against — reporting `except: pass` as a
store — is not reachable under the emitter's own rule, because a store in a
handler never happens at all: the refusal for a name only a handler stores
survives the change, since the join is then reached from the body alone.

**The direction that keeps the change honest:** a name a handler stores and the
body does not is read from a register nobody wrote, on this backend, and that
must stay a refusal. It is `try: sink(n) / except E: p = 1 / return p` — which
`read_before_store` already refuses, and would go on refusing, because the
join's IN set is computed from the body's exits and the body does not store `p`.

## How much of the corpus is in an arm that is not emitted

Counted by walking the AST (`TryStmt` nodes and their `handlers`), over the same
two roots the sweep uses — this repository, and
`new-modular/Mojo/stdlib/std`:

| | `try` statements | handler arms | `with` statements |
|---|---|---|---|
| repository (400 files) | 1007 | **921** | 972 |
| stdlib (252 files) | 78 | **78** | 11 |

**839 of the repository's `try` statements have at least one handler, in 208
files**, and 78 of the stdlib's 78 do, in 29 files. So this is not a rare shape:
roughly two thirds of the `try` statements a sweep meets have an arm that
contributes nothing to the image.

## The exact next step, in the order it should be done

1. **Decide the question the pin was decided without: is the answer "a handler
   arm is dead" or "a handler arm is not ours".** They differ in the message.
   "Dead" is false of the language and true of the image; "not ours" is the
   honest framing and it is also what `no_public_api_reason`'s rule wants — the
   refusal must not be false about the file. Refusing a `try` that HAS a handler
   arm whose body stores anything, by name, is the version that is true of both:
   it never says a program the language accepts is broken, and it does not let
   a store in a dropped arm pass for a store.
2. **Then either drop the handler arms from the CFG or refuse the construct.**
   Dropping them is a two-line change in `_build_cfg`'s `TryStmt` arm — stop
   `run(getattr(h, "body", …))` and stop adding `arm_exits` — and it flips
   `one_handler_stores_refused`. Refusing instead is `model.py`'s
   `no_public_api_reason` shape: a refusal that names the arm and says what to
   do. **The second is safer to land**, because the first makes every
   `try`/`except` file buildable while continuing to drop its arms, which is the
   silent half of this finding.
3. **The silent half needs its own decision and it is the bigger one.** A
   handler body with a side effect — `except E: close(f)`, `except E:
   return fallback()` — produces an image that skips it, and no check in the
   pipeline sees that. The options are: emit the arm as straight-line code after
   the body (wrong, but no worse than dropping it and it at least keeps the
   store), or refuse every `try` with a handler whose body is not `pass` /
   `raise` / `continue`. Either is better than silence, and the measurement a
   reader needs is the same one this file already has: 921 arms in this
   repository alone.

`bugs/FORMAL_read_before_store_what_is_left.md` lists the `read_before_store`
consequences; it does not own this, because this is an emitter decision with a
diagnostic consequence, not an analysis question.

## What is already pinned, and stays

`read_before_store`'s own rows for the shapes that do NOT involve a handler —
`every_handler_stores_is_dominating`, `try_else_clause_runs_only_when_the_body_
completed`, and the whole `finally` set from `706f3f8b` — are about arms that
either store on every path or are never emitted at all, and none of them
changes. `test_formal_run.py`'s `every_handler_stores_is_dominating` builds and
RUNS `try: p = 1 / except Exception: p = 2 / printf("p=%d", p)` and gets `p=1`,
which is the body talking and is correct for this backend — but it is also the
only row in the tree that executes a program with a handler in it, and it passes
for a reason that has nothing to do with the handler.