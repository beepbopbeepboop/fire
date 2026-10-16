# FORMAL: a subscript whose BASE is itself a subscript of a known integer list SIGSEGVs, where the same subscript of a named integer is refused

**Area:** FORMAL (the container family's base classifier —
`formal/model.py::scalar_container_base_evidence`, asked from both emitters'
single subscript/slice/membership/for-in choke point). Found 2026-10-05 on
`work/formal40-1-r2` while fixing
`FORMAL a comprehension element container aliases every iteration`.

**Status: NOT FIXED, and the refusal for this construct EXISTS and is correct —
the base classifier simply never asks the question for this one base shape. Not
mine: the fix belongs to whoever takes the container base classifier, and §"Why
the obvious fix is wrong" is the measurement that says the obvious fix refuses a
program that works.** This document exists because the symptom is a **fault with
a green build and no diagnostic**, which is the class the whole refusal family
was written to prevent.

## What was run, what was seen, what was expected

```console
$ cat .tmp/ce/kk4.mojo
def main():
    v = [1]
    s = v[0][0]
    print(s)
    return 0
main()
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ce/kk4.bin .tmp/ce/kk4.mojo
Built: .tmp/ce/kk4.bin  [arm64/macho]
$ .tmp/ce/kk4.bin ; echo "rc=$?"
Segmentation fault: 11
rc=139
```

| | answer |
|---|---|
| CPython | `TypeError: 'int' object is not subscriptable`, exit 1 |
| arm64 | **SIGSEGV**, exit 139, nothing on stderr |
| x86-64 | **SIGSEGV**, exit 139, nothing on stderr |

**Not the print's doing.** `print(v[0][0])` is refused, and it is refused for
the PRINT — "cannot tell whether SubscriptExpr is a string or a number" — so a
reader who stopped there would conclude the construct is guarded. The arithmetic
and `printf` spellings are not: measured, all of these SIGSEGV on both
architectures with the build green.

## The refusal for this construct exists, and names the fault

One line's shape different — the base is a NAME:

```console
$ cat .tmp/ce/nn.mojo
def main():
    x = 1
    y = x[0]
    printf("%d", y)
    return 0
main()
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ce/nn.bin .tmp/ce/nn.mojo
build: a subscript of `x` asks for a container element, and `x` is a value this
function bound to an integer. … Measured on BOTH architectures, this builds,
links, and then dies of SIGSEGV at run time with the build green …
```

**That message describes this bug exactly**, which is the finding: the rule, the
wording and the measurement all exist and none of it fires when the base is a
`SubscriptExpr`. `scalar_container_base_evidence` has three arms — a
`TYPE_KIND`, a struct FIELD declared `NON_CONTAINER_SLOT_KINDS`, and a scalar
LITERAL — and a subscript is none of them.

## Why the obvious fix is wrong, and this is the part worth keeping

The obvious fix is a fourth arm: *the base is a subscript whose element kind is
a scalar*. Measured on this tree, `kind_of` already answers that:

```console
$ python3 -c "… ValueKinds(main).kind_of(v[0]) …"
kind_of(v[0]) = int          own_shape_kind(v) = list:int
NON_CONTAINER_SLOT_KINDS = ['int', 'type']
```

and `own_shape_kind`'s table says a kind returned from a construction is a
CLAIM while `INT_KIND` is the default — so `v[0]` looks like evidence.

**It is not, and the program that says so builds and answers correctly today:**

```console
$ cat .tmp/ce/ap.mojo
def main():
    v = [1]
    v.append([2])
    s = v[1][0]
    printf("%d", s)
    return 0
main()
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ce/ap.bin .tmp/ce/ap.mojo && .tmp/ce/ap.bin
Built: .tmp/ce/ap.bin  [arm64/macho]
2
```

`own_shape_kind("v")` is `list:int` for that function too — the LITERAL said so
and the `append` never retracted it — so an arm keyed on it refuses a program
that is right on both architectures. **The evidence an append-able literal
offers is not evidence about what the list holds after the append**, and closing
that is a statement about the append-capacity scan (`_scan_list_caps` /
`blob_nodes_bound_to` already know which names are appended to) rather than
about the kind table. That is why this is filed and not fixed: the fix is real
and it is in the kind table's blind spot, not in a missing `if`.

Two neighbours, measured, so the next reader does not re-derive them:

| shape | today | note |
|---|---|---|
| `rows = [[1, 2], [3, 4]]; s = rows[0][1]` | **2 on all three** | the inner base really IS a list, and it answers |
| `v = [[1]]; s = v[0][0]` | **1 on both backends** | a list of lists answers too, so the fault needs the element kind to be a SCALAR — which is also why the obvious arm's gate is the right gate |
| `v = []; v.append(1); s = v[0][0]` | SIGSEGV both | `own_shape_kind(v)` is `None` here, so the kind table claims nothing and this is the same fault reached with no evidence at all — the case a fix keyed on evidence alone would leave behind |

## Why it is worth a document rather than a note

The formal path's discipline is "a construct with no representation is REFUSED,
never emitted", and the message quoted above is that rule being applied and
measured. This is the one failure mode it cannot produce: the refusal is written,
the measurement is in it, and the program does not get it. The sweep's
`backend-crash` class is **0 files** over 738 today, and this program is what
puts a 1 there.

It is also reachable from ordinary code rather than from a fuzzer: it needs a
subscript whose base is an integer, which is one ragged-table indexing mistake
away in any program that walks a list of lists without binding the row first —
and the corpus deliberately reads nested subscripts through a local (see
`FORMAL len of a subscript of a list of lists is an int` §"Why the corpus does
not generate it"), which is why 738 files never produced one.

## The exact next step

**Two questions, and the second is the one that decides it.** In
`formal/model.py`, the kind of `v[i]` is
`subscript_element_kind(base_kind)` — already correct — and what is missing is a
way to say that the `base_kind` it read is a CLAIM *and* that no statement of the
function appended to the base. `ValueKinds` already holds the first half
(`own_shape_kind`) and `blob_nodes_bound_to` / `_scan_list_caps` already hold the
second; the reader that wants both is `scalar_container_base_evidence`, which is
the ONE place the two backends ask, so a fix there lands on both machines at once
and cannot make them disagree.

Ask the append half FIRST and the shape above, because it is the one that
refuses a working program: with it, `v = [1]` alone is evidence and
`v = [1]; v.append([2])` is not, which is exactly the distinction the corpus row
turns on.

The regression net belongs in `test_formal_value_model.py`'s `REFUSALS`, whose
rows pin a refusal by needle, and **the needle should be the sentence the named
base already produces** — so a fix cannot pass by refusing something else. It
needs one ORACLE row beside it, for `v = [1]; v.append([2]); s = v[1][0]`, which
answers `2` today: that row is what stops the fix from being the one-arm version
this document measured as wrong.

**Do not add a `KNOWN_DIVERGENCES` row to `tools/formal_fuzz.py`.** A divergence
row records an answer as accepted, and this is a fault: there is no answer.