# CODEGEN: a `List[String]` filled only inside a callee reads back as ints in the caller

## Status (2026-09-28 — OPEN, reproduced, cause not investigated)

```mojo
def fill(kept: List[String]):
    kept.append(String("cde"))

def main():
    var kept: List[String] = []
    fill(kept)
    print(len(kept[0]))      # 6581285 (garbage)   -- CPython: 3
    print(kept[0])           # 4364882704 (a pointer) -- CPython: cde
    print(kept[0] == "cde")  # True                -- correct
```

If the elements are appended in the same function as the reads, all three lines are
correct. Ownership on/off makes no difference (checked with every ownership analysis
disabled), so this predates the ownership work. The element type of a list is recorded
by the code that lowers `append`; a caller that only sees the list through a call never
learns it, so `kept[0]` is typed as an int: `len` of it reads the pointer's bits as a
list header, `print` formats it with `%ld`, and only the comparison (which dispatches on
the string literal side) still works.

Found while building a regression test for string ownership: reading a `List[String]`
element with `len`/`print` is unreliable across a call boundary, so the test compares
with `==`.

## Done when

The repro prints `3`, `cde`, `True`. Likely fix: honour the `List[String]` annotation on
the declaration/parameter as the element type instead of relying on `append` sites.
