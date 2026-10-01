# FORMAL_debug_assert_bracket_has_no_lowering: `debug_assert` is a builtin the interpreter has and the formal backends have neither spelling of

**Status: OPEN, and it is now the terminal cause for the 80 files that
`L[T]()` used to block.** Found by `construct:type-name-as-value-2` on
2026-10-01, measuring what `std/collections/binary_heap.mojo` reaches on the
new-modular stdlib once the type-application refusal is gone. Not fixed here:
it is a different construct (a builtin with no lowering at all), it is not in
that claim, and the measurement says its own value is small — §3.

## 1. What I ran and what I saw

`formal/build.py` bound `callees` twice, so the subscript-callee exemption that
makes `List[Self.T]()` build was dead code; `69f20418`'s fix was voided by a
merge. With that repaired (`e4ee0de7`), the terminal cause of the eighty
dependents moves. Measured on eight of them, x86-64, **cold CAS both sides**
(`GMOJO_HOME` at an empty directory, per `FORMAL_sweep_cache_ignores_imports.md`):

```
$ python3 tools/formal_sweep.py --arch x86_64 -j 4 -t 90 $(cat .tmp/dep8.txt)
```

| | before | after |
|---|---|---|
| all 8 files | `binary_heap.mojo: BinaryHeap___init__: 'List' has no home: the module-level symbol table is empty for this unit …` | `binary_heap.mojo: debug_assert[…](…) calls a name this unit does not compile, so the brackets cannot be bound.` |
| class | `codegen/dependency` x8 | `codegen/dependency` x8 |
| coverage | 0/8 | 0/8 |

**8 of 8 moved, all onto the same message.** So `L[T]()` is no longer what any
of them is blocked by, and the row is now this one. (The file itself:
`test_formal_type_application.py`.)

## 2. Why `debug_assert` is refused — and it is not a specialization problem

Both spellings fail, for two different reasons, and neither of them is about
brackets:

```
$ cat .tmp/t4.mojo                          # the bracketed spelling
def main(n: Int) -> Int:
    debug_assert[assert_mode="safe"](n > 0, "n must be positive")
$ python3 fire.py build --formal --no-prove .tmp/t4.mojo
build: debug_assert[…](…) calls a name this unit does not compile, so the
brackets cannot be bound. …

$ cat .tmp/t5.mojo                          # the BARE spelling
def main(n: Int) -> Int:
    debug_assert(n > 0, "n must be positive")
$ python3 fire.py build --formal --no-prove .tmp/t5.mojo
build: t5.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: debug_assert. …
```

The second one is the informative one: **the bare spelling gets past every
check and emits a `BL debug_assert`.** Nothing in `formal/build.py`,
`formal/model.py`, `formal/arm64_codegen.py` or `formal/x86_64_codegen.py`
mentions `debug_assert` at all — the only occurrence in the whole `formal/`
tree is one clause of a comment in `model.py:14688`, listing it among "names
that really are read where there is no storage", which is the wrong half of the
story now that the bare call is not refused there either. The link audit caught
the dangling symbol, which is why this is a refusal and not a wrong image, but
it caught it by accident of ordering.

`debug_assert` is a **builtin** here, and the interpreter has it:
`myinterpreter.py:3010`

```python
def _debug_assert(cond, *args):
    if not cond:
        raise AssertionError("debug_assert failed" + (": " + str(args[0]) if args else ""))
self.scope.define('debug_assert', _debug_assert)
```

So this is not "the stdlib is not on this path" — it is one builtin the
reference engine implements in six lines and this backend does not implement at
all.

## 3. What it is worth, measured, before anyone invests

**Ceiling: 0 files, and the 80 are behind a second limit anyway.**

`binary_heap.mojo` is two constructs deep past this one, not one. Probed by
copying it to `.tmp/bh_nodebugassert.mojo` with the two `debug_assert[…](…)`
statements deleted — a throwaway copy, the stdlib is not modified:

```
build: len(self._data) — this slot's DECLARED type is 'List[Self.T]', so the
lowering is settled … `S()` does not run `__init__` on this path (premise a
zero-argument S() does not run __init__) … a field with no class-level default
is a word of zeros: the count word would be read from address 0. Measured with
the kind taken from the declaration anyway, on BOTH architectures: this built,
ran, and died with SIGSEGV (exit 139).
```

That is the same blocker `bugs/FORMAL_dylib_export_gate_ceiling.md` §3 and §8
already identified and already measured at ceiling 0 — on the OLD stdlib, where
`L[T]()` was working and `binary_heap.mojo` reached `len(self._data)` directly.
So this doc does not reopen that finding; it explains why the new-modular tree
reaches it one step later.

`binary_heap.mojo` also carries a third thing this backend has no lowering for
and no diagnostic for: `self._data = List[Self.T](capacity=capacity)` in its
second `__init__`, which `model.blob_constructor_with_operands_refusal` names
correctly ("a blob that has to HOLD n element(s) needs a frame reservation whose
size is a value this compiler does not have at layout time") but which is a
refusal by construction, not by accident.

**Scale of the family, for whoever picks it up:** 61 call sites in 23 files of
the new-modular stdlib — 28 bracketed in 8 files, 33 bare in 15. Zero `.mojo`
files in this repository's own tree use it, which is why no suite step has ever
reached it.

## 4. The exact next step

In order, because each is a prerequisite for the next and the last two are
other people's neighbourhoods:

1. **`debug_assert` needs a lowering, and the lowering is small.** The
   interpreter's is: evaluate the condition, and on false print the first
   message and exit non-zero. `printf` is already the answer for the message on
   both backends, so `cond ? 0 : fail("…")` is the whole construct. Where it
   belongs is a question, not a given: a `model` predicate naming it plus an arm
   in each `_emit_call`, the way `model.empty_blob_constructor` and its two
   `_emit_type_constructor` arms are one predicate and two arms — **not** a
   name list in `build.py`, for the reason `model.EMPTY_BLOB_CTORS`'s comment
   gives (a hand-kept list is a list that goes stale the day the table it
   shadows grows a name, and the stale name is then refused as "no
   representation", which reads as a fact about the target).
2. **The bracket then has to bind, and for this one it can.** `assert_mode` is
   declared `StaticString` — a `char *`, which is one word on this path — so
   `debug_assert[assert_mode="safe"](c, m)` is expressible as
   `debug_assert("safe", c, m)`, which is precisely what
   `model.specialization_call_refusal`'s own words say a specialization's
   brackets are ("ordinary leading arguments the call site evaluates and passes
   first"). What is missing is the **declaration**: `debug_assert` is declared
   in `std/builtin/debug_assert.mojo` and `binary_heap.mojo` has no imports at
   all, so `_callee_defs` has nothing in hand. Either a builtin declaration
   table next to step 1's predicate, or `binary_heap.mojo` gaining the import
   (its own decision, and the stdlib is outside this worktree).
   `cpu_only: Bool` and `_use_compiler_assume: Bool` are the other two template
   parameters and are also one word each.
3. **The variadic messages are `FORMAL_string_value_model.md`'s question, not
   this one's.** `*messages: *Ts` with `write_to` on each element is a
   variadic of values, and `bugs/FORMAL_ast_module_subset.md` /
   `FORMAL_known_limits.md` §1.1 are the neighbourhood. **A `debug_assert` with
   NO messages lowers without touching any of that**, and 61 call sites is a
   count, not a requirement: decide deliberately whether the first landing is
   `debug_assert(cond)` and the formatting comes later, rather than discovering
   the variadic halfway through.
4. **What it will not buy, so nobody measures it again.** Even with all three
   above, the eighty files stay refused behind `len(self._data)`'s
   `S()`-does-not-run-`__init__` premise (§3, and
   `FORMAL_dylib_export_gate_ceiling.md` §8). Land this for the construct and
   for the diagnostics, not for the count.

## 5. Reproducing this

Everything above is two commands and a throwaway copy; no gate, no sweep of the
full tree, no bootstrap.

```
python3 tools/memslot.py --gb 8 --label probe -- \
    python3 fire.py build --formal --no-prove .tmp/t4.mojo -o .tmp/t4.arm64
python3 tools/memslot.py --gb 8 --label probe -- \
    python3 fire.py build --formal --no-prove .tmp/t5.mojo -o .tmp/t5.arm64
python3 tools/memslot.py --gb 8 --label probe -- \
    python3 fire.py build --formal --no-prove .tmp/bh_nodebugassert.mojo -o .tmp/bh2.arm64
python3 tools/memslot.py --gb 8 --label probe -- \
    python3 tools/formal_sweep.py --arch x86_64 -j 4 -t 90 $(cat .tmp/dep8.txt)
```