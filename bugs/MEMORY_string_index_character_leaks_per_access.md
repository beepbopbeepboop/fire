# MEMORY: `s[i]` on a string leaks a character allocation per access

## Status (2026-10-01 — OPEN, measured, NOT fixed. Reproduces identically on pristine `origin/master`)

`gimplerunner`'s own case `gimple_char_scan_allocates_nothing_per_character`
fails on the compiled path:

    FAIL  gimple_char_scan_allocates_nothing_per_character:
          stdout '4800000\n' (want '4800000\n'), peak RSS 246.7 MB (limit 60)

**The answer is right.** The output is exactly what CPython prints and what the
test wants; only the memory ceiling is blown. So this is a leak, not a
miscompile, and it is invisible to any exit-code or stdout check — the case is
in the bounded-memory family for exactly that reason.

## This is upstream's, not a merge artefact

Measured by running the case's own program in a detached worktree at
`origin/master` (`d0796643`) with none of our changes present: **identical** —
same stdout, same 246.7 MB peak, to the decimal. Our tree's only differences
from `origin/master` are nine files (`git diff origin/master..master`), and
none of them touches string indexing or allocation:

| file | what ours does | could it leak per character? |
|---|---|---|
| `mojo/backend_gimple/module_gen.py` | renames a local `_lens` -> `_elens` (a `MojoSet*`/`MojoDict*` name collision) | no — offload path only |
| `mojo/backend_gimple/emit_infra.py` | renames a local that shadows a STRUCT TYPE NAME to `_var_` | no — fires only on such a shadow |
| `mojo/backend_gimple/emit_stmts.py` | generator context managers now register a teardown | no — needs a generator CM |
| `gimple_codegen.py`, `runtime/fire_runtime.h` | comments only | no |

So `gimplerunner` is red **upstream**, and a red `gimplerunner` here is not
evidence that the merge resolutions lost anything. That was worth establishing
before touching anything, because the merge had just resolved three conflicts
in this same area.

## Measured shape of the leak

Same program, iteration count scaled, peak RSS read the way the test reads it:

| iterations | peak RSS | delta |
|---|---|---|
| 25,000 | 32.2 MB | |
| 50,000 | 62.9 MB | +30.7 MB |
| 100,000 | 124.1 MB | +61.2 MB |
| 200,000 | 246.7 MB | +122.6 MB |

Linear in the iteration count, intercept ~1.5 MB: a per-access leak, not a
fixed cost. `scan` walks a 16-character string (`"(x[x{}x]) " * 8`), so

    122.6 MB / 100,000 iterations = ~1.23 KB per call = ~77 bytes per `s[i]`

77 bytes is about one `char *` plus a 1-character buffer plus whatever the
shared-character bookkeeping carries — consistent with the leak being the
character object itself, not the index arithmetic.

## Why it is believed

The case immediately after this one in `test_gimple_runner.py` names the cause
in its own comment, for the *concat* half of the same mechanism:

> now that the character strings are shared and never freed: `out + ch` frees
> its own conversion temp only for a number, never for a character

So sharing a character string and never freeing it is deliberate — it has to
be, because freeing a shared character would be a use-after-free, and the
runner scribbles freed memory so a wrong free there would change the output or
crash. The consequence is that a character string must be **owned by something
with a lifetime**, and `var c = s[i]` in a loop creates one per access with no
owner: nothing frees it, and the loop cannot be the owner because the
character is not retained.

The gap is therefore not "the free is missing" — it is that the shared
character has no refcount or owner, so the loop that materialises one cannot
release it.

## Next step

1. Decide what OWNS a shared character string. The candidates, in order of how
   much machinery they assume:
   - **Refcount on the shared character**, freed when the last holder drops.
     Correct, and it is the only option that keeps sharing; the cost is a
     non-trivial conversion and a `mojo_str_release` the compiler must emit on
     every path that drops a character, which is a real ABI addition.
   - **Stop sharing single characters**: `s[i]` returns a fresh 1-char string
     the caller owns, and `out + ch` keeps its existing free. Simplest, and it
     gives the leak an owner for free — at the cost of an allocation per access,
     which is exactly what this case is asserting should not happen, so it does
     not satisfy the case. Listed only because it bounds the problem.
   - **A per-call scratch buffer for index results**, valid until the next
     index on the same string, mirroring what `_fmt_int`'s transient pool
     already does for integer keys (doc/MEMORY.html §4.1). No ABI change, and
     it composes with the sharing; the hazard is that "valid until the next
     index" is a sharp edge the codegen has to respect, and
     `var c = s[i]` in a loop is the easy case, not the hard one.

2. Whichever it is, `s[i]` is the only site that has to change for THIS case;
   the general question is every other read of a shared character.

3. This is a compiled-path and runtime change, so it owes a full `make gate`.
   The step that catches it is `gimplerunner` itself, so the gate cannot be
   green until it lands — `gimplerunner` is in `check` and is not
   `expect=`-marked, and it should not be: the case is real and the fix is
   wanted.

## Evidence

- `origin/master` in a detached worktree, the case's own program: 246.7 MB,
  limit 60, output correct. Same as our tree.
- The four-point scaling table above, on our tree.
- `git diff origin/master..master` — the nine differing files, none of them in
  this path.
