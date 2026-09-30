# FORMAL_returned_frame_caller_owned_block: `return <frame>` lowers, and what the 30 files it named actually do now

`FORMAL_wide_receiver_by_reference.md` §"Round 2" designed the caller-provided
block, `formal/model.py` landed the caller's layout, and
`bugs/INTERFACE_REQUEST_4_to_formal_build.md` asked the integrator to assign
`formal/build.py` so the gate could come down. **This is that work.** The
returned frame is built in a block the CALLER owns; the 19 sweep findings that
say "frame address escapes: returned by its creator" are zero.

The short version of what it is: a function that returns a frame gains ONE
hidden trailing argument — the address of a block the caller reserved — builds
the object **in** that block instead of in one of its own, and returns it. A
caller-side block per call site, in the caller's own scratch, outlives the
callee by construction; nothing about the callee's lifetime enters into it.

## What landed, and where

| what | where |
|---|---|
| which local a function builds or forwards and returns, as a whole-image FIXED POINT over the call graph | `formal/model.py` `returned_frame_holder`, `returned_frame_forward_bindings` |
| the block the CALLER reserves, per call site | `formal/model.py` `struct_returned_frame_sites` (extended: it now covers `var q = f()`, see below) |
| the constructions that build the returned object, in the callee | `formal/model.py` `returned_frame_constructor_sites` |
| the calls that must be handed this function's OWN block, so a chain of forwarders builds one object | `formal/model.py` `returned_frame_forward_sites` |
| the one reader of "is this statement a binding of a single name" | `formal/model.py` `frame_binding_target`, `frame_binding_value` |
| the nested-frame offsets inside a block, to every depth | `formal/model.py` `struct_block_children` |
| the escape gate, and the one new edge in the holder fixpoint | `formal/build.py` `_check_frame_escapes`, `_frame_receivers` |
| five refusals | `formal/model.py` `returned_frame_{entry,library,shape,ambiguous,blob}_refusal`, `returned_frame_convention_refusal` |
| the codegen | `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`: `_ret_block_sites`, `_ret_fwd_sites`, `_ret_recv_sites`, `_emit_site_base` / `_emit_block_base` |
| the cases | `test_formal_returned_frame.py` — 12 differential + 8 refusal, both architectures built and executed, each differential case compared against CPython |

## The three decisions, and why each went the way it did

### Building in place, not copying into the block

The landed design (`FORMAL_wide_receiver_by_reference.md` §Round 2, and
`bugs/INTERFACE_REQUEST_4_to_3_contracts.md`, which states the contract the
codegen would be written against) says: *"`return <frame>` becomes 'copy the
block to that word, return that word'."* This does not copy. The constructions
that build the returned object write **through the hidden word** instead, so:

* a copy construction `S(x)` inside a returning function needs no re-basing at
  all — the copy loop's destination is the caller's block;
* `p.x = 3` after `p = Point()` lands in the caller's block for free, because
  `p` holds the caller's block address;
* **a nested frame's ADDRESS does not need re-basing**, which is the part that
  made the copy version expensive. `struct_nested_frame_fields` places a nested
  frame inside its owner's block and stores its address in a slot; a byte copy
  of the block would leave that address naming the OLD block, at every depth.
  Building in place has no such step because there is no second block.

This is the one place this change deviates from the written agreement, so it is
worth being explicit that the deviation is a **simplification, not a different
convention**: the caller still reserves the block, the callee still takes the
hidden word, `return <p>` still returns that word, and the caller still reads
the object back through the address it passed. The Lean predicate
`bugs/INTERFACE_REQUEST_4_to_3_contracts.md` asks for is stated over "the
returned-frame convention", which this is.

### Forwarding, which is what makes the common shape work

The shape most real code has is not a factory, it is a forwarder:

```python
def twice(a):
    var q = make(a)
    q.x = q.x + 1
    return q
```

`twice` builds nothing, so "redirect its construction sites" has nothing to
redirect. It forwards: **the call that binds the returned holder is handed THIS
function's own block**, so the object is built in the outermost caller's
scratch and every link in the chain agrees. A chain of three forwarders builds
one object in `main`'s block, and no copy is taken anywhere.

The rule is deliberately narrow — only the sites that bind **the returned
holder** forward — because a call site that did not forward would be handed a
block of its own, and two objects in one function is the case where sharing one
block would be a wrong answer rather than an optimisation. That case is
`two_returned_frames_in_one_function_are_two_blocks` in the test file, and it
is there because it is the one that found the bug below.

### `var q = f()` reserved no block, and `q = f()` did

`struct_returned_frame_sites` matched `AssignStmt` and not `VarDecl`. A callee
called from a `def` binds its result with `var` almost always, so **the shape
the corpus actually uses reserved nothing** and the callee wrote the object into
a block nobody owned. The landed function had never been read by the emitters,
so nothing had failed loudly; it was simply a layout nobody used.

Four readers needed "is this statement a binding of a single name" and three had
grown their own version, which is how this happened. They are now one function,
`model.frame_binding_target`, and `formal/build.py`'s copy of the constructor
walk (`_constructor_bindings`) is a two-line delegation to the model's.

## Two bugs this change found, both in its own new code

Both were found by running programs, and both are the shape
`CLAUDE.md` calls the worst outcome: a build that succeeds and computes the
wrong thing.

**1. Every block was zero bytes.** The caller half needs a predicate
`(callee_name, bound_name) -> struct`, and both backends handed it
`f._returned_frame`, which is the `(holder, struct)` **plan**.
`struct_frame_block_bytes` was then called on a tuple, answered 0, and every
call site in a function got offset 0 — so the second object a function built
overwrote the first, and the program exited 0 with the wrong answer. Both
architectures, because both read the same table. Caught by
`two_returned_frames_in_one_function_are_two_blocks`, which exists in the test
file for exactly this and is the reason the file has a "both architectures"
rule.

**2. `_emit_frame_base` leaves the address in `X9`, and the call site pushed
`X0`.** arm64's block-base convention is that the base goes in `X9` because
every block store recomputes it there; the argument push reads `X0`. With one
returned frame in a function the two happened to hold the same word often enough
to pass; with two, it did not.

**3. `dict.get` was handed to a predicate that takes two arguments.**
`struct_returned_frame_sites`'s contract is
`returns_frame(callee_name, bound_name) -> struct`, and both backends passed
`self._returns_frame.get`. `dict.get` takes `(key, default)`, so a MISSING
callee answered with the second argument — the bound NAME — and **every call in
a module that declares a multi-field struct was treated as returning a frame**:
a zero-byte block reserved for each, and its address pushed as a ninth argument
into a register the callee never reads. Five extra instructions per call, so
every program's ANSWER was unchanged and no image was byte-identical to what it
had been; and where a module also had an eight-argument call the ninth push
crossed the ABI limit and the program was **refused for an argument it never
had**:

```
build: call wide(): 9 arguments exceeds the 8 the formal arm64 ABI passes in
registers (one of which is the block this callee returns a frame in)
```

for `def wide(a, b, c, d, e, f, g, h)` bound with `var r = wide(...)`, in a
module that also declares a two-field struct. On x86-64 the same bug refuses a
SIX-argument call.

This one is worth recording for what it says about the LANDED code rather than
about the new code: `struct_returned_frame_sites` and its two-argument contract
were already on the tree, with ten cases in `test_returned_frame_layout.py`, and
nothing failed — because that file's `_returns` helper is a real two-argument
closure and the arity was never the thing under test. **A documented parameter
list is not a check**, and the only thing that turned this into a failure rather
than 20 bytes of dead code per call was an arity boundary.

None of the three is a reasoning error; each is "a table read at two places", "a
register convention read at two places", or "an argument list read at two
places", which is why the fix for each is ONE reader rather than a second
check.

## The measured effect on the 30 files this cause blocked

**Row 5 (`frame address escapes: returned by its creator`) is 19 → 0.**
Re-swept on this tree, over exactly the 30 files the map's rows 5 and 9 name
(`tools/formal_sweep.py -j 6 -t 180`, arm64):

| | before | after |
|---|---|---|
| `returned by its creator` | 19 | **0** |
| `aliased out of a method` | 11 | 11 |
| PASS | 0 | **0** |

Where each of the 19 landed:

| where | files | what it is |
|---|---|---|
| `not-answerable/host-import` | 4 | `ast_rewriter.py`, `imports.py`, `ownership_destruct.py`, `test_dispatch_phase_c.py` — the refusal is gone and the file is now stopped by an import of `dataclasses` / `platform` / `gimple_codegen`. **This is the direction of drift that flatters a number**: they leave the `codegen` denominator without becoming answerable, and `dataclasses`/`platform` have Mojo-side implementations other workers own. |
| `not-answerable/system-module-call` | 1 | `fault_tolerance.py` — the frame reaches `dataclasses.asdict(...)`, which has no body on this target. Also out of the denominator, also a fact about the target. |
| MLIR | 3 | `mma_nvidia_sm100.mojo`, `python.mojo`, `time.mojo` — a **documented permanent limit** (`FORMAL_known_limits.md` §2), not work |
| `inlined_assembly` | 1 | `path.mojo` — likewise permanent (§1) |
| a TYPE name placed as a value | 2 | `_format_float.mojo`, `mma.mojo` — the map's row 2 (`List[T]()`), where `binary_heap.mojo`'s `'List' has no home` is the module-level symbol table |
| receiver passed at argument position 0 | 2 | `suite.mojo`, `tools/suite.py` — the map's row 4 |
| one parameter, two kinds of value across call sites | 2 | `testing.mojo` and one other — the holder-agreement check |
| a slot's declared type is not declared by its struct | 2 | `test_async_execution.py`, `test_generators.py` — the map's row 10, another worker's claim |
| receiver stored in a container | 1 | `formal/x86_64_endtoend_test.py` |
| **the entry point** | 1 | `bootstrap_test_classes.mojo` — below |

### The one file that looked like it would pass, and must not

The instruction for this work was to measure the marginal effect by hacking the
refusal away and re-sweeping, and that measurement says **one** of the 30
reaches `pass`: `bootstrap_test_classes.mojo`. It does not, and the reason is
worth more than the number:

```python
class Point:
    def __init__(self, x, y): ...

def create_point():
    p = Point(3, 4)
    return p
```

There is no `main`, so `model.entry_function` makes `create_point` the entry and
the startup stub branches to it with **one** word — the test input. A hidden
block word would be whatever the second argument register happened to hold, and
the object would be built there. With the refusal lifted and no convention
underneath, this file builds and produces an image that faults or reads
whatever was in that register; with the convention underneath, it is refused by
name (`model.returned_frame_entry_refusal`).

**So the honest figure for this work is 0 files reaching `pass`, and the
difference between 0 and the 1 a lift-without-an-implementation reports is
exactly the bug that version would have shipped.** Every other file in the
family is behind a construct that is somebody else's row, or behind a
documented permanent limit.

## Still open, and what it is

* **Row 9 — a frame that arrived as a PARAMETER and is handed back
  (`def fwd(p): return p`, 11 files).** Refused, and it stays refused:
  `FORMAL_frame_receiver_handoff.md` §8 argues the lifetime is sound (the
  creator is always an ancestor of the caller) and then declines to lift the
  refusal, because the argument is about the whole image and two of the
  channels it leans on are not yet refusals — a module-level write, which
  returns 10 on arm64 and 0 on x86-64 where the source says 5. That is
  `construct:module-global-storage`, another worker's claim. Filed as
  `FORMAL_returned_frame_received_is_still_refused.md`.
* **The proof-side predicate.** `bugs/INTERFACE_REQUEST_4_to_3_contracts.md` is
  a `lib/Refine.lean` callee-contract variant for a function that writes a
  frame into a block it was handed. Not this change's file, not done, and the
  emitters are written against the shape it states.
* **`formal/x86_64_endtoend_test.py` and `fire_compiler.py`**: the two whose next
  refusal is a shape this change did not touch — a frame address stored in a
  container, and a returned name bound by two constructors. The second is now
  `returned_frame_ambiguous_refusal` and its message says which two.

## A neighbouring bug this change fixed on the way

`model._container_binding_names` collected "names this body binds to a
container" from `AssignStmt` only, so `var xs = [1, 2]` did not count and the
one hop it exists to make — `tmp = [...]; self.x = tmp` — did not happen for a
`var` binding. Premise (B1) is enforced with it. Measured over the whole
corpus (631 files, parsed, `struct_field_container_writes`): **4 files** are
affected (`device_context.mojo`, `fire_compiler.py`, `mojo/middle/solvers.py`,
`test_llm/test_llm.py`), and all four still report the SAME first refusal as
before, so no file changed class. It is in this change because the returned
block needed the same one hop and would otherwise have had its own copy.

`struct_block_children` is here for a second reason: `_emit_nested_frame_init`
recursed by unpacking `struct_nested_frame_fields`'s **three**-element tuples as
four, so a nested frame of a nested frame raised `ValueError` on both backends.
The offsets are now computed once, by the same function that computes the bytes
reserved, and both emitters read them.

## Verification

| command | result |
|---|---|
| `python3 test_formal_returned_frame.py` | **PASS=21 FAIL=0** — 12 differential against CPython, 8 refusals, one structural guard, both architectures built and executed |
| the same file on the **pre-change** tree (`git archive 53f89ae7` into a scratch root, this file dropped in) | **`PASS=3 FAIL=18`** — the 3 are `refuse_a_received_frame_handed_on` (labelled a GUARD in the file: refused before and after, for the same reason) and the two arity cases, which are guards for bug 3 below and are correct on a tree that has no convention at all |
| the same file on the **intermediate** commit `e2892699`, which had the codegen but not bug 3's fix | **`PASS=16 FAIL=5`** — the four structural failures, both arity cases (`9 arguments exceeds the 8 …` / `7 … exceeds the 6`), and the two cases whose messages landed in the next commit |
| `python3 test_formal_run.py` | `PASS=387 FAIL=0`, after `byref_refuse_returned` was re-pointed (see below) |
| `python3 test_formal_frame_len.py` | `PASS=10 FAIL=0`, unchanged |
| `python3 test_formal_imports.py` | `PASS=41 EXPECTED=0 FAIL=0`, unchanged |
| `python3 -m unittest test_formal_sweep_truth` | `Ran 31 tests … OK`, unchanged |
| `python3 test_formal_link_accounting.py` | `133 passed, 0 failed`, unchanged |
| `python3 test_returned_frame_layout.py` | `10 passed, 0 failed`, unchanged |
| `formal_sweep` over the 30 files, arm64 | table above |
| **byte-identical Mach-O for a program that already worked**, before vs after, same output filename in each tree | arm64 **byte-identical** (51152 bytes), x86-64 **byte-identical** (51360 bytes) — for a 60-line program with two structs, five methods, a list blob, a loop and a `printf` |

The byte-identity measurement is what found bug 3, and it is worth recording
WHY it found it: `CLAUDE.md` asks for byte-identical output from a
behaviour-preserving change, this is a change that must be behaviour-preserving
for every program that does not return a frame, and twenty bytes of extra
instructions per call site is not that. The answers were all still right — which
is exactly the shape the map's §3 warns about, where a file's verdict does not
move and the image underneath it does.

**`byref_refuse_returned` was re-pointed, not deleted.** It asserted that
`return p` from the function that built `p` is refused. That was true and is no
longer, so the case moved out of `test_formal_run.py`'s refusal list into
`test_formal_returned_frame.py` as a demonstration, with a comment at the old
position saying why. Leaving it would be a test asserting the opposite of the
truth; deleting it without saying so would be worse.

`test_formal_run.py`'s two `returned from a … receiver` cases are UNCHANGED and
still pass: those are row 9, not row 5.
