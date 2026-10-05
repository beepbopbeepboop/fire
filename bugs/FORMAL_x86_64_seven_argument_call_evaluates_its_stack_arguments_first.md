# FORMAL_x86_64_seven_argument_call_evaluates_its_stack_arguments_first

**Class:** codegen. **Area:** `formal/x86_64_codegen.py::_emit_call`'s
`placement` split — the loop that stores the STACK-passed arguments
(`for k in range(n_stack): … self._emit_expr(arg)`) and the register-argument
`reg_plan` loop after it. **x86-64 only**: the same source on arm64, and the
same source through the gimple path (`gimple_codegen.py`) on both
architectures, is right (measured below).

**Status: OPEN, measured, reproducible in eleven lines. Not fixed here** — it is
outside the claim of the session that found it
(`bug:FORMAL_the_host_import_rows_after_glob_ranked_by_what_they_actually_spell`,
which is `formal/hostmods/random.mojo`), and a change to a backend's call
lowering owes a full `make gate`, which that session is not permitted to run.

## The measurement

A module-level counter, a function that increments it, and one call with SEVEN
integer arguments whose arguments are that call. `join` builds a positional
7-digit number out of its parameters, so a permutation of the arguments cannot
hide:

```mojo
var _n: Int = 0

def tick() -> Int:
    global _n
    _n = _n + 1
    return _n

def join(a0: Int, a1: Int, a2: Int, a3: Int, a4: Int, a5: Int, a6: Int) -> Int:
    return a0 * 1000000 + a1 * 100000 + a2 * 10000 + a3 * 1000 + a4 * 100 + a5 * 10 + a6

def main() -> Int32:
    printf("%lld\n", join(tick(), tick(), tick(), tick(), tick(), tick(), tick()))
    return 0
```

`python3 fire.py build --formal --no-prove -o .tmp/argord .tmp/argord.mojo && .tmp/argord`:

| | answer | right? |
|---|---|---|
| arm64 | `1234567` | yes |
| **x86-64** | **`2345671`** | **NO** |

`2345671` is `join`'s parameters in source order EXCEPT that the first call's
result arrived in the SEVENTH slot: argument 7 was evaluated first, so it got
counter value 1, and arguments 1-6 got 2-7. **The arguments are not misplaced —
each one is stored in the slot its index names — they are EVALUATED in the wrong
order.** That distinction is the whole bug and it is why nothing about the
emitted code looks wrong.

The threshold is the ABI's, not the emitter's: with **six** arguments both
architectures answer `123456` for the six-argument spelling of the same program,
and with **seven** only x86-64 is wrong. SysV AMD64 passes the first six integer
arguments in `RDI/RSI/RDX/RCX/R8/R9` and the rest in the caller's frame, so
argument 7 is the first one this emitter places in the reserved outgoing area.

## It is not about `printf`, and not about variadics

| variant | arm64 | x86-64 |
|---|---|---|
| `join(tick() x 6)` — 6 arguments, one in registers | `123456` | `123456` |
| `join(tick() x 7)` — 7 arguments, one on the stack | `1234567` | **`2345671`** |
| `printf("%lld %lld … %lld", tick() x 6)` — 8 arguments, 2 on the stack | right | **`2 3 4 5 6 1`** |
| `printf("%lld … %lld", tick() x 7)` — 9 arguments | refused (arm64's own 8-argument limit) | **`3 4 5 6 7 1 2`** |
| `join(a…a)` with LITERAL arguments, 8 of them | right | right |
| `printf(…, math.isqrt(i*i) x 7)` — 8 arguments, side-effect-free calls | right | right |

So: not the callee (a plain function is affected), not the format string, and
**not "more than six arguments" by itself** — literal arguments and
side-effect-free calls are fine at any count this ABI allows. It needs an
argument whose evaluation is observable, and it needs that argument to be one of
the ones this emitter evaluates early.

## Why the emitter evaluates them early, and what the fix has to keep

`formal/x86_64_codegen.py::_emit_call` reserves the outgoing-argument area first
(`stack_bytes = _SLOT * ((n_stack + 1) // 2)`) and its own comment says the
stack arguments are stored FIRST and that this is load-bearing:

> The STACK arguments, each stored into the slot the callee will read it from.
> FIRST is load-bearing and not a style preference: the register arguments below
> are spilled with a `_SLOT` push each, so evaluating them first would move RSP
> 96 bytes down and every `[RSP + 8k]` above would land in the register spill
> area instead of the reserved outgoing slots.

That reasoning is correct and the fix cannot simply reverse the two loops — it
would reintroduce exactly the `[RSP + 8k]` aliasing the comment describes, which
is a wrong-value bug of the same family.

The two requirements are in direct conflict **only because evaluation has side
effects**: source order says argument 7 is evaluated after argument 1, and the
RSP invariant says argument 7 must be stored before argument 1 is spilled.

**THE NEXT STEP, concretely: evaluate EVERY argument in source order into the
reserved outgoing area, then move the register half out of that area into
`ARG_REGS` at the end.** The area is already reserved as a multiple of 16 with
`[RSP + 8k]` slots the callee reads; make it large enough for the register
arguments too (`n_stack + len(reg_plan)` slots), store argument `j` at
`[RSP + 8 * placement[j].slot]` in source order, and after the last argument is
stored, load `ARG_REGS[i]` from its slot. That satisfies both: no push happens
between two stores, so no `[RSP + 8k]` can move, and the side-effect order is
the source's. The load-at-the-end loop is the same shape the existing code
already uses in reverse (`POP` into `RAX` then move across), so it is a
reordering rather than new machinery.

**What a fix has to be pinned by**, because the shapes that catch it are
specific: the seven-argument positional `join` above (both architectures, an
answer compared against the source's own digit order), the eight- and
nine-argument `printf` spellings (which is where a corpus notices first — see
below), and a six-argument call that must STAY right, since a fix that reserves
more space can break the case that works today.

## Why it matters more than the two callers that found it

Found while writing `formal/hostmods/random.mojo`'s differential corpus: seven
`random.randrange(a, b)` calls in one `printf` answered `2 3 4 5 6 1` on
x86-64 where CPython's `random` gives `1 1 0 1 1 0 0`. That is the shape of a
whole class: **any formal program on x86-64 whose call has seven or more integer
arguments and whose arguments call something with a side effect silently
computes a permuted argument list** — and a permuted argument list is not a
crash, not a wrong exit status and not a refusal, it is a program that computes
something the source does not say.

`formal/x86_64_codegen.py` already refuses a `printf` with more than eight
arguments on arm64 ("puts 1 of them past the 8 argument registers"), which is why
the `printf` spellings above do not reach the arm64 rows at nine arguments —
**the arm64 guard has no x86-64 counterpart for this**, because on SysV the
seventh argument has a home.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label argord -- \
  python3 fire.py build --formal --no-prove --backend=x86_64 -o .tmp/argord.x86 .tmp/argord.mojo
.tmp/argord.x86            # 2345671; arm64 answers 1234567

# and the gimple path, which is RIGHT on both (the scope statement above)
python3 tools/memslot.py --gb 8 --label argord -- \
  python3 fire.py build -o .tmp/argord.gimple .tmp/argord.mojo && .tmp/argord.gimple
```

Peak memory 0.1 GB for every build above; the program is eleven lines and builds
in under a second on both architectures.