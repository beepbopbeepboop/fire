# FORMAL_function_value_refusal_is_defined_twice_and_the_later_one_wins: a red test on current master, from two commits writing the same function

**Class:** a duplicate definition, not a missing capability. Two branches each
wrote `formal/model.py::function_value_refusal` and Python keeps the LAST one in
file order, so one of the two messages has never been reachable.
**Area:** `formal/model.py`, and the wording assertion in
`test_formal_specialization.py::a_function_read_as_a_value_is_refused_by_name`.

Found 2026-10-03 while running the formal suites over the `with`-protocol work.
It is NOT that work's: both definitions predate it and the failure is on master.

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_specialization.py
  FAIL  a function read as a value is refused by name
formal specialization: PASS=11 FAIL=1
```

and the same program by hand, both architectures:

```
$ cat .tmp/fv2.mojo
def plain(v: Int32) -> Int32:
    return v + 100
def call_it(f, x: Int32) -> Int32:
    return f(x)
def main() -> Int32:
    return call_it(plain, 5)

$ python3 fire.py build --formal --no-prove [--backend=x86_64] -o … .tmp/fv2.mojo
build: main: 'plain' is a FUNCTION, and a function is not a value on this path:
  it has no representation here — a value is one 64-bit word and a function is a
  code address, …                                          [arm64 and x86_64]
```

## What I see

`grep -n "^def function_value_refusal" formal/model.py` prints **two** lines, and
`inspect.getsourcelines` says the one at the SECOND line is what the emitters get:

| line | added by | its message says |
|---|---|---|
| 24209 | `cbc4f512` (2026-10-03 03:47) | "`plain` is a function of this module **read as a VALUE**, and …" |
| 25886 | `2814868e` (2026-10-03 02:07) | "`plain` **is a FUNCTION**, and a function is not a value on this path: …" |

Both are on master (`git show master:formal/model.py | grep -c "^def
function_value_refusal"` → 2), in the same relative order, so the shadowed one
is dead code there too. The test asserts four things about the message and one of
them is the shadowed wording:

```python
        check("read as a VALUE" in text, …)     # ← the 24209 wording
        check("no value of a function" in text, …)
```

so the row is red on master, and it is red for a reason no reader of either
commit would guess: both messages are honest and both name the construct, and
the assertion is pinned to the one Python never returns.

## What is next

One of the two definitions, deleted, and the assertion matched to whichever
survives. Which is which is a judgement that belongs to the holder of
`FORMAL_functools_is_unbuildable_as_a_host_module` (`formal13-4`), which owns
both commits' subject; the 25886 wording is the one that names the missing
representation first and the repair last, which is the order
`model.external_call_value_refusal` uses, and the 24209 one is the one the test
wants. Either is defensible; what is not defensible is shipping both and letting
the file order decide.

**Why this is filed rather than fixed:** it is another claim's lane and the fix is
one deletion plus one string, but a deletion in `formal/model.py` next to two
commits that are still being merged is a conflict for a change nobody can review
as anything but "which message did you keep".

## What this is NOT

Not a wrong diagnostic. Whichever definition wins, the refusal names the name the
reader wrote, says a first-class function has no representation on a path where a
value is one 64-bit word, and gives the repair — verified on both architectures,
which is why the only red thing here is one assertion about wording.
