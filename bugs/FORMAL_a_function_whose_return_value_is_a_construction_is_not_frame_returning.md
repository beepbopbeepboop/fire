# FORMAL_a_function_whose_return_value_is_a_construction_is_not_frame_returning: `def mk(v: Int) -> A: return A(v, v + 1)` is a word-returning function, and every caller believes it

**Area:** FORMAL (`formal/build.py`, `_frame_return_status`). Found 2026-10-03 on
`work/formal13-4` while closing
`bugs/FORMAL_eq_dispatch_two_call_operands_are_not_a_frame_address.md`, whose
third step turned out to be one clause further upstream than that document
guessed. **The fix is small, was measured working, and is NOT landed** — §4 says
why, and the blocker is a separate pre-existing x86-64 defect that would turn a
refusal into a wrong answer.

## What I ran

`.tmp/ow/f1.mojo`, `struct A` with two `Int` fields, and the three shapes a
programmer writes:

```python
struct A:
    var x: Int
    var y: Int

    def __eq__(self, other: A) -> Bool:
        if other.y != self.y:
            return False
        return self.x == other.x

def mk(v: Int) -> A:
    return A(v, v + 1)          # ← the return value is a CONSTRUCTION

def main(n: Int) -> Int:
    var t = mk(1)
    printf("x=%d y=%d eq=%d", t.x, t.y, 1 if t == mk(1) else 0)
    return 0
```

`python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal
--no-prove -o .tmp/ow/f1 .tmp/ow/f1.mojo`, on both backends, with CPython on the
same text as the oracle.

## What I saw

On the tree as it stands, **both** architectures refuse program `f1` — and the
refusal is about a NAME, for a decision made about the FUNCTION:

```
build: main: 't.x' is a field access through 't', and this path has no way to
  say what 't' holds. A field is lowered three ways and which one applies is
  decided …
```

CPython prints `x=1 y=2 eq=1`. The same `mk` spelled with a name in it —

```python
def mk(v: Int) -> A:
    var a = A()
    a.x = v
    a.y = v
    return a
```

— works on arm64 (`x=1 y=2 eq=1`) and is what every existing case in
`test_formal_run.py` and `test_formal_returned_frame.py` is written in. So the
difference between a function this path can answer and one it cannot is one clause
about the `return`, and it is a clause about a node nobody writes a name for.

`_frame_return_status`'s docstring says a value is frame-valued "in exactly two
ways… a bare name that holds a frame address, and a call to a function already
known to return one", and then adds that "a copy construction … is a frame in THIS
function's own scratch and is copied out by the same convention when it is
returned". **The second half of that sentence describes machinery that is not
reached**: with the classification `_RETURN_WORD`, no caller reserves a block
(`model.struct_returned_frame_sites` asks the same table), so the callee's
`_emit_frame_return` — the copy — is behind the same flag and never runs. What is
actually returned is the address of a frame in an activation that has already been
reclaimed.

That it goes unnoticed is the second measurement. A comparison that dispatches on
such a call reads the dead block and is right anyway, because nothing has reused
it yet:

| program | CPython | arm64 | x86-64 | |
|---|---|---|---|---|
| `mk(1) == mk(2)` (`__eq__` returns True) | 1 | 1 | 1 | right, and for no reason |
| `t == mk(2)` with a field-wise `__eq__` | 0 | 0 | **1** | the x86-64 half is §4's blocker |

So the shape answers "right" or "wrong" depending on what the program does next
with the dead block, which is the outcome this project treats as the worst one
available: an answer that is right for no reason.

## The exact change, measured and then not landed

One clause in `_frame_return_status`, after the `returns_by_name` lookup, and a
recogniser beside it:

```python
                built = _returned_frame_construction(value, callee,
                                                     structs_by_name, fn_names)
                if built is not None:
                    frames.append(([built], _expr_spelling(value), None))
                    continue
```

```python
def _returned_frame_construction(value, callee, structs_by_name, fn_names):
    st = (structs_by_name or {}).get(callee)
    if st is None or not M.struct_is_framed(st):
        return None
    if not M.call_lowers_as_framed_construction(
            callee, structs_by_name or {},
            len(value.args or []) + len(value.kwargs or []), fn_names):
        return None
    return st
```

Every part of the recogniser is asked in the EMITTER's terms on purpose:
`call_lowers_as_framed_construction` is the build pass's one reader of the
construction-vs-type-conversion dispatch order (so `String()` in a module that
declares `struct String` stays a word), and `struct_is_framed` is what keeps a
one-field struct a word — its construction binds a plain word that IS the field,
and that is the "copy construction" the docstring means. No emitter change is
needed: `_emit_frame_return` on both backends emits the source expression and then
copies `struct_frame_block_layout`'s bytes, which is exactly right for a
construction's address.

**Measured with it in place**, both backends, against CPython on the same text:

| program | CPython | arm64 | x86-64 |
|---|---|---|---|
| `f1` — `t.x`, `t.y`, `t == mk(1)` | `1 2 1` | `1 2 1` | `1 2 1` |
| `t == mk(2)` — the `eq_dispatch` doc's `c` | `True True` | `1 1` | `1 1` |
| `mk(1) == 5` | refused by the audit | refused, naming `5` | same |
| `mk(1).x`, `mk(2).x` | `1 2` | `1 2` | `1 2` |
| **`var t = mk(1); var u = mk(2); t.x, u.x`** | `1 2` | `1 2` | **`2 2`** |

The last row is the whole reason this is filed and not landed.

## Why it is not landed: it exposes an x86-64 wrong answer that is currently a refusal

The last row is a use-after-free in the picture above, on one architecture only:
two names bound to returned frames both read the LAST block. It is pre-existing and
measured on the pre-change tree (`var t = mk(1); var u = mk(2); printf("%d %d",
t.x, u.x)` → `2 2` on x86-64 before any edit here), but today every program that
would show it is REFUSED instead, because the holder analysis cannot establish
`mk` as frame-returning. Adding this clause removes the refusal and leaves the
wrong answer, on x86-64 only — a net loss on that machine and exactly the
"a better DIAGNOSIS and a worse INSTRUMENT" trade the surrounding code argues
against.

That defect — two names bound to returned frames reading one block, on x86-64
only — was filed with its own measurements and next step and is now FIXED, so
its doc is deleted with it; what it cost is recorded by
`test_formal_returned_frame.py`'s four arrangements of two live returned
frames. It is in the same neighbourhood as
`FORMAL_x86_64_a_field_of_a_returned_frame_in_an_argument_position_segfaults`
(thirteen `test_formal_returned_frame.py` cases, all x86-64), which is a SIGSEGV
where this one is a wrong number; if they turn out to be one emitter bug, fix that
first and this clause becomes landable immediately, because everything else here is
measured.

## What a taker should check

1. `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_returned_frame.py`
   — 13 x86-64 failures before, and they must not become more.
2. `test_formal_run.py` (801 cases), `test_dataclasses_formal.py`,
   `test_struct_formal.py`, `test_formal_frame_return_overloads.py`,
   `test_formal_receiver_position.py`, `test_formal_method_param_field.py`,
   `test_formal_bracketed_method_field_set.py`,
   `test_formal_specialized_method_call.py`, `test_formal_read_before_store.py`.
   All measured green with the clause in place.
3. **The ABI budget is the expected second-order effect.** A frame-returning
   callee takes one hidden trailing word, so a construction-returning function
   called with eight arguments now hits
   `model.returned_frame_convention_refusal` (six on x86-64). That is the correct
   direction — a refusal rather than a dropped word — but it is a refusal that did
   not exist before, so it belongs in the release note rather than being
   discovered by a program.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove -o .tmp/ow/f1 .tmp/ow/f1.mojo
build: main: 't.x' is a field access through 't', and this path has no way to …
```

`formal/build.py::_frame_return_status` is the only function to change;
`_frame_valued_calls` and `struct_returned_frame_sites` already know how to read a
frame-returning call at a call site, and they are what starts working once this
clause exists.