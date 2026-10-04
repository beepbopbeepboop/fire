# FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it: `os.environ` is modelled, and what the 4-file sweep row is actually worth

**Status (2026-10-03, `work/formal15-os-environ`): the MODEL LANDED and the row is
re-measured. `formal/hostmods/os` has a real `os.environ` — a snapshot of the
process environment in `malloc`'d memory, with `count`/`key`/`value`/`find`/
`get`/`get_or`/`has`/`set`/`del`/`keys`/`items`/`free` over it — differential-
tested against CPython on BOTH architectures against a FIXED environment. The
sweep row moves 4 files off the `os.environ` refusal and **0 files to `pass`**,
and the ceiling is measured rather than projected: rewriting the two in-file
files by hand lands each on a DIFFERENT row's refusal. Read §2 before spending
anything on this; the object is not the thing that is missing any more.**

This is the row `bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §4.2 measured as
"the next wall behind the module-slot row", and it was the largest unowned
codegen row's next step. Here is what it was worth, measured.

## 1. What the refusal was, and what it was standing on

The b8 sweep filed four files with `os.environ` as the terminal cause, two of
them in-file and two of them through `determinism_trace.py`:

```
CODEGEN: determinism_trace.py          os.environ reads 'environ' out of the imported module `os`
CODEGEN: test_coro_runtime.py          __module_body__: the same
CODEGEN/DEPENDENCY: mojo/backend_gimple/emit_resolve.py   (via determinism_trace.py)
CODEGEN/DEPENDENCY: mojo/middle/resolve_shared.py         (via determinism_trace.py)
```

and the module's own header said why, in two halves that were both wrong:

> `environ` IS ITS THREE FUNCTIONS. A process environment is a `char **` in the
> C library's data, and enumerating it needs a buffer walk this path cannot do.

**The walk was available.** It is a loop over an array of pointers, which is
`listdir`'s own shape over `readdir`, and the ARRAY is reachable: the C library's
`environ` is an exported data symbol, and `os/_syscalls.mojo`'s
`fs_environ_vec` asks the dynamic loader for it at RUN time —
`dlopen(0, 0)` then `dlsym(h, "environ")`, then one dereference each for
`char ***` → `char **` → `char *`. Measured on both architectures; the reason it
is `dlsym` and not libSystem's own `_NSGetEnviron()` is in that function's
docstring: a callee whose name begins with `_` cannot be bound on this path,
because `model.libc_source_name` strips the underscore and macOS's `dlsym` does
not put it back (`bugs/FORMAL_libc_call_whose_name_starts_with_an_underscore.md`,
which is a two-one-line fix in the LINKER and therefore not a light change).

**The spelling was the other half**, and it was already written down in the same
header: "`getenv`, `putenv` and `unsetenv` are the whole of what can be reached,
and they are what `os.environ.get(k)` and `os.environ[k]` have to become". That
was true and it was not enough, because `os.environ.get(k)` has a second half
`os.environ[k]` that `getenv` cannot answer at all — `getenv(3)` conflates "set
to nothing" with "not set", and a dict does not.

So the model is a dict-shaped object, and it is the `[count][element]…` blob
`listdir` already established rather than a third convention. Two divergences are
recorded rather than papered over, both of them CPython's own and both measured
on every run of `test_formal_os_backing.py`'s `environ_view`:

  * `os.environ[k]` raises `KeyError` and there is no unwinder, so `[]` is `get`
    and answers 0. 0 and `""` are different words, which is how a key set to the
    empty string is told from a key that is not there — and `os.getenv` cannot
    tell them apart, which is the whole reason the view is not three functions.
  * `os.putenv(k, v)` moves `os.getenv(k)` and leaves `os.environ` holding what
    it held, because CPython's `putenv` does exactly that. `environ_set` is
    `os.environ[k] = v` and DOES call `putenv`, as CPython's `__setitem__` does.

`environ_set` returns the blob the caller must KEEP rather than a status,
because growing a view is a `realloc` and a `realloc` may move it.

**No admitted contract, and that is a decision rather than an omission.**
`formal/admitted.py` is for a host object a freestanding image does not have —
a second process, a thread, a dynamic loader for foreign code, an embedded
interpreter. The process environment is none of those: libSystem has it, the
image has it, and every answer in the model is computed rather than assumed. An
`@admitted` here would have made every `os`-importing file in the sweep move to
`built-with-admitted-contracts`, which is counted in the denominator and never
as a pass — so the honest answer and the cheap-looking one differ, and this took
the honest one.

## 2. What the row is worth: 4 files off the refusal, 0 to `pass`, measured

Both files whose terminal construct is IN the file, rebuilt on this tree with the
CPython spelling left as written:

| file | before | after this change | after rewriting the spelling BY HAND |
|---|---|---|---|
| `determinism_trace.py` | `os.environ reads 'environ'` | the value-member refusal, naming the operations | `_f.write()`: a method on a struct field, receiver classified `int` |
| `test_coro_runtime.py` | `__module_body__: os.environ reads 'environ'` | the same | `sys.exit()` — which §4.6 of the b8 map records as DELIBERATELY not taken |

(the two `codegen/dependency` files are still dependency-refused on
`determinism_trace.py`, with a new inner message.)

**So an importer rewrite of `os.environ.get(k, d)` buys 0 passes**, and that is
the finding rather than an omission: the next construct for each file belongs to
a different row (`FORMAL_tempfile_context_manager…`'s neighbourhood for
`determinism_trace.py`'s file writer, and the `sys.exit` export decision for
`test_coro_runtime.py`). The same conclusion §4.1 reached for `binary_heap.mojo`
and the same shape as its price: measured, and not a patch.

**What a reader can do TODAY, with no compiler change at all**, is the thing the
next row's owner should know, because it is two lines per file:

```python
# determinism_trace.py:45, 52
_v = os.environ.get('MOJO_TRACE', '')        ->  os.environ_get_or(os.environ(), 'MOJO_TRACE', '')
# test_coro_runtime.py:21                    ->  os.environ_get_or(os.environ(), 'CC', 'cc')
```

That is not a compiler feature and should not be made into one at a measured
ceiling of zero passes. It IS worth doing to those two files on their own merits
if the rows behind them are ever closed.

## 3. The trap this cost an hour, written where the next reader will hit it

`p + k` on a base with a DECLARED pointee is **byte** arithmetic on both
architectures, for every pointee width, in every spelling of the expression —
while `p[i]` scales by that width:

```
b: Pointer[Int64]; b + 1  ->  base + 1     (not base + 8)
                         b + n  ->  base + n
                         b + 1 + 2 * n  ->  base + 1 + 2n
                         b + 8 * (1 + n)  ->  base + 8 + 8n
```

`bugs/FORMAL_pointer_value_model.md` §9 records this as OPEN with the next step
(`_emit_binop` is the hottest site in both backends and scaling there wants its
own diff). **What that document does not say is that the guard only fires at a
DEREFERENCE**: `_offset_scale` refuses `q = p + k` when the pointee is wider
than a byte AND something dereferences `q`, and passing the same expression to a
libc call is not a dereference, so nothing refuses it. `memset(b + 1 + 2 * n, 0,
16)` on an `Int64` blob compiles, links, runs, and zeroes sixteen bytes at offset
107 of a blob whose pairs live at 8-byte offsets — which is what this change's
first draft did, and the symptom was a `SIGSEGV` in `strlen` on the seventh
environment variable of a blob nothing had touched.

Both facts are now in `formal/hostmods/os/_syscalls.mojo`'s header next to the
`memmove`/`memset` calls they apply to.

**Status 2026-10-03 (`work/formal16-5`): §4's first item is DONE — `copy()`,
`pop(k, d)` and `clear()` are in the module, differentially tested against
CPython over the same fixed environment on both architectures.** All three were
"either the same blob with a different spelling or a second representation", and
all three turned out to be the first kind. `environ_copy` duplicates every key
and value (an ALIASING copy would answer every count and key correctly and still
be wrong: `environ_free` on either blob would free buffers the other hands out —
the double free `environ_keys`' own docstring records being measured the hard
way). `environ_pop` is ONE call rather than the "two calls each" this section
predicted, because `str_dup`-ing the value before `environ_del` releases the
pair is what makes the answer survive the removal — the alias `environ_get`
hands back a moment earlier is freed memory by the time a caller prints it.
`environ_clear` is in place and answers a STATUS, the asymmetry with
`environ_set` being the layout talking: adding a pair can move the allocation and
removing pairs cannot.

Counted over the tree, which is what decided the order: `get` 109 (already
there), `pop` 11, `copy` 9, `setdefault` 6, `update` 2, `keys`/`items` 2 each
(already there), `clear` 1. What is left in this section is `environb`,
`update`, `popitem`, the exported slot, and the bare `os.environ` read — and
`setdefault`/`update` stay two calls each, which is a limit of one-word returns
and not a missing function.

**§3's last sentence is CORRECTED for `update` by §4's second status block:
`update` is ONE call** (`environ_update`), because the limit is one word per
CALL and `update`'s whole answer is that one word. `setdefault` stays two,
since it must hand back the value it kept as well as the view.

**The row's own verdict does not move: 4 files off the `os.environ` refusal and 0
to `pass`**, because these are the SPELLINGS a file has to be rewritten into, not
constructs it was waiting on. §2's two-line rewrites are still the whole of what
a reader can do today.

## 4. What is still NOT modelled, and each one's cost

  * **An EXPORTED SLOT** — one view every importer shares rather than one per
    caller. `FORMAL_module_state_no_storage.md` §(2), an ABI change, and a
    project. Until it exists `environ()` is `1 + 2n` allocations per CALL, which
    is why every docstring on the functions says to call it once and keep it.
  * **`os.environb`** (the bytes view), `dict(os.environ)`, `os.environ.copy()`,
    `.update()`, `.clear()`, `.popitem()`. Each is either the same blob with a
    different spelling or a second representation, and `environ_del`'s in-place
    reordering is why a second one is not free.
  * **`pop`/`setdefault`/`update`** are two calls each rather than one, and the
    CPython-spelling table at the head of the section says which two. That is a
    limit of one-word returns rather than a missing function, and it is the same
    bargain `walk`'s `_walk_fill` makes with the index in and the index out.
  * **`os.environ` as a VALUE read bare** (`v = os.environ`) is still refused —
    it is `FORMAL_module_state_no_storage.md`'s §(4) and no part of this change
    touches it. `module_attribute_refusal`'s answer for it is unchanged.

**Status 2026-10-03 (`work/formal18-5`): `update` is ONE call, and the doc's
"two calls each" was wrong for exactly that one.** §3's list — `environb`,
`update`, `popitem`, the exported slot — is one shorter. `environ_update(e,
other)` is in the module, differentially tested against CPython on both
architectures, and it is ONE call for the reason §3 gives the wrong answer: the
limit that forces `setdefault` to be two calls is **one word of answer**, and
`update` has nothing to say except the view, so the view IS the answer and the
loop that grows the blob happens inside where the intermediate pointers are
words in a register. `environ_set`'s contract carries over exactly — the answer
is `e` itself when every key was already there, a new blob when one was appended,
0 when the growth failed — because a `realloc` may move.

Two things the implementation had to answer that the doc did not ask about:

  * **`update(e, e)` is safe, and that is a property of the layout rather than
    a promise.** Every key of `other` is then already a key of the receiver, so
    every store takes `environ_set`'s in-place branch, no `realloc` happens and
    `e` never moves. That is not sufficient on its own — `environ_set` frees the
    old value buffer before duplicating the new one, and for an aliasing
    `other` the buffer being freed is the one being read — so the value is
    duplicated first on that path and released after. `d.update(d)` is legal in
    CPython and leaves every pair equal, so it is a case rather than a refusal.
  * **A `0` receiver is a `0` and a `0` other view changes nothing**, which is
    CPython's rule for updating from an absent mapping.

What is left in §3 was `environb`, `popitem`, the exported slot and the bare
value read. **`popitem` was here and is WRONG (2026-10-04,
`work/formal19-4`) — see the Status at the head** — so what is left is
`environb`, the exported slot and the bare value read. **And the row's own
verdict still does not move: 4 files off the
`os.environ` refusal and 0 to `pass`.**

## 5. The one thing here that is not the environment

Publishing `environ` turned a precise refusal into a misleading one, and the
repair is in `formal/model.py` (`dylib_value_member_refusal`, one arm of
`dylib_extern_symbol`, so one code path for both backends): while `environ` was
NOT an export, `os.environ.get(k)` was refused as an ATTRIBUTE READ naming the
module and what it publishes; once it IS an export the spine link resolves, the
callee exemption bows out, and the chain reached the bind audit as "the image
would bind 1 symbol(s) that nothing provides: os.environ.get" — a claim about
the link line, which is not what is wrong with it. The new arm says the chain is
a call through a VALUE and names the operations, read off the parent's own
export table (`environ_count` … `environ_value`), because a dylib publishes
functions and cannot publish the objects they are called on.

Two cases in `test_formal_module_attr.py` pin it on a module of the test's own,
including the empty half — a value with no `thing_*` beside it must be reported
as publishing no operation rather than handed a repair that does not exist.

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label os-env -- python3 test_formal_os_backing.py -v environ_view
python3 tools/memslot.py --gb 8 --label os-env2 -- python3 test_formal_os_backing.py -v environ_view_empty
python3 tools/memslot.py --gb 8 --label dt -- python3 fire.py build --formal --no-prove \
    -o .tmp/dt determinism_trace.py
```

The two sweep rows behind the rewrite table in §2 are re-measured on
`bugs/FORMAL_sweep_work_map_2026-10-03_b8.md`; a re-sweep belongs to whoever
runs the gate. `test_formal_os_backing.py` is 58/58 on this tree (three
consecutive full runs) and `test_formal_os.py` is 5/5 groups.

**Re-measured 2026-10-03 (`work/formal18-5`) with `environ_update` in:** the
same two counts — 58/58 and 6/6 groups — and `environ_view` is now **77 answers
per architecture** against CPython rather than the 58 it had, the 19 new ones
being the `update` rows of §4's second status block. `test_formal_os.py` is 6/6
groups here rather than 5/5: its `blob` group is the sixth and is not a recent
addition.