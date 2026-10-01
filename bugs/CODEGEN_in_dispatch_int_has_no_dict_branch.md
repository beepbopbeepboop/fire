# CODEGEN: `x in <dict>` is always False when the dict's static type is erased — `mojo_in_dispatch_int` has no dict branch

## Status (2026-09-29 — OPEN, measured; one line of runtime, not fixed here)

`mojo_in_dispatch_str` answers `x in <container>` for a dict, a list and a set.
`mojo_in_dispatch_int` — the same question asked with both operands erased to
`int64_t`, which is what the codegen emits whenever the container's static
type is unknown — answers for a LIST and a SET and has no dict branch at all,
so a dict falls off the end and the answer is `0`. Silently.

## What was run, and what it showed

```python
def look(names, d):
    var n = 0
    for name in names:
        if name in d:
            n = n + 1
    return n

def main() raises:
    var names = ["f0", "f1"]
    var d = {}
    d["f0"] = 1
    d["f1"] = 1
    print(look(names, d))          # CPython prints 2
```

`python3 fire.py build -o .tmp/wlB .tmp/wlB.py && .tmp/wlB` prints **0**,
exit 0, no diagnostic.

The generated C shows the whole chain: passing a container to a function erases
its static type (`int64_t d` in the callee, `look(names, _t11)` with the dict
cast to `int64_t` at the call site), so `name in d` lowers to the generic
dispatcher rather than the typed `mojo_dict_contains`:

```c
  _t5 = mojo_list_get_int (names, _t3);
  name = (int64_t) _t5;
  _t7 = (int64_t)d;
  _t8 = (int64_t)name;
  _t6 = mojo_in_dispatch_int (_t7, _t8);     /* -> 0 for a dict */
```

and in `runtime/fire_runtime.c`:

```c
int mojo_in_dispatch_str(int64_t container, char *needle)
{
    if (mojo_is_registered_dict(container)) return mojo_dict_contains(...);
    if (mojo_is_registered_list(container)) return mojo_list_contains_str(...);
    if (mojo_is_registered_set(container))  return mojo_set_contains_str(...);
    return 0;
}

int mojo_in_dispatch_int(int64_t container, int64_t needle)
{
    if (container == 0) return 0;
    if (mojo_is_registered_list(container)) return mojo_list_contains_int(...);
    if (mojo_is_registered_set(container))  return mojo_set_contains_int(...);
    return 0;                                  /* <-- no dict branch */
}
```

This is the failure mode the runtime's own comment on `mojo_in_dispatch_str`
warns about ("it silently inverts program logic: every membership test against
a cross-module container global answered 'no'") — reintroduced for dicts on
the int view.

## Blast radius

Every `x in <dict>` in compiled code where the dict is not a local with a
known static type: a dict built in one function and tested in another (the
shape above), a dict read from a module global through an `int64_t` accessor,
a dict returned from a call. The result is a False, not a crash, so it
compiles, links, runs and exits 0.

Note the asymmetry that makes it easy to miss in review: the SAME source
compiled with the dict kept local lowers to `mojo_dict_contains` and is
correct. That is why `mojo/middle/coro.py`'s new wait-descriptor worklist keeps
all four of its tables local (see its comment on dicts-not-sets) — not a
preference, a requirement.

## Exact next step

One line in `runtime/fire_runtime.c`:

```c
    if (mojo_is_registered_dict(container))
        return mojo_dict_contains((MojoDict *)(uintptr_t)container, (char *)(uintptr_t)needle);
```

with a test beside the ones that already exist for the str dispatcher: build a
dict in `main`, pass it to a function, and require the membership test to
answer True. There is no such test today, which is why the str dispatcher's
dict branch is there and the int one's is not.