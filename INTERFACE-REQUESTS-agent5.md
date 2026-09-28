# INTERFACE REQUESTS — agent [5] (the formal path links the runtime dylib)

Round: the five-agent round of 2026-09-28, `FORMAL.md` §11.2. Write set for
this agent: `formal/model.py`, `formal/build.py`, `formal/imports.py`. Nothing
below is an edit to a file this agent does not own.

Measured outcome, for the integrator's summary: **0 → 138** word-shaped
`mojo_*` calls reachable from a formal Mach-O image (156 on the link line, 18 of
those needing a heap handle the path cannot produce). Full derivation and the
three open ceilings in `bugs/FORMAL_runtime_library_on_the_link_line.md`.

---

## [5] → integrator · `test_formal_run.py` · BLOCKS THE GATE

**This is the one that matters: it is a red test on `fire.py build --formal`,
caused by the change, and it pins the old behaviour.**

`test_formal_run.py:527`, case `gimple_runtime_print_refused`, asserts that
`mojo_print("hi")` is REFUSED. It now builds, links and runs — which is the
entire point of the change, and is verified on both architectures
(`test_formal_runtime_link.py`).

**WHAT** — replace the case with a run case, and fix the section comment above
it so it no longer says a formal image "links libSystem and nothing else". This
diff is **not hand-written**: it is the output of applying the change and running
the file, and it takes `formal-run` from **338/2 to 339/1** — the one remaining
failure being the pre-existing `limit_ellipsis_function_body`.

```diff
@@ -511,11 +511,17 @@ CASES = [
     #
     # `mojo_*` is the ABI of the OTHER backend's C runtime (runtime/
     # fire_runtime.h, runtime/fire_sqlite3.h), and a program written against it
-    # spells those entry points in the source. A formal image links libSystem
-    # and nothing else, so each of these used to emit a BL against a symbol
+    # spells those entry points in the source. A formal image used to link
+    # libSystem and nothing else, so each of these emitted a BL against a symbol
     # nothing defines: the build reported success and the program died in the
-    # loader. A `refuse:` case, so the assertion is that BOTH architectures
-    # say no with the same words.
+    # loader. A formal build now puts the per-architecture `mojo_*` library on
+    # the link line when the program names a word-shaped entry point of it
+    # (`formal/build.py`'s `_runtime_library_for`), so a `mojo_*` call splits
+    # three ways: linked, refused for its TYPES, and refused because this
+    # library does not export the name. The two `refuse:` cases below are the
+    # second and the third; a numeric case is the first, and the assertion there
+    # is that BOTH architectures AGREE — which `refuse:` also asserts, for the
+    # other two.
     ("gimple_runtime_sqlite_refused",
      "def main():\n"
      "    var db = mojo_sqlite3_open(\":memory:\")\n"
@@ -523,12 +529,17 @@ CASES = [
      "    return 0\n",
      "refuse:is an entry point of the gimple backend's C runtime", None),
     # `mojo_print` rather than `print`, for the file that spells the runtime's
-    # own name. Same namespace, same answer.
-    ("gimple_runtime_print_refused",
+    # own name. Same namespace, OPPOSITE answer, and this is the case the whole
+    # phase-2 payoff turns on: every type crossing this call is one 64-bit word
+    # — a `char *` is a value on this path, because a string is an interned
+    # `char *` with no header — and the per-arch runtime library is on the link
+    # line, so this is no longer a refusal but an image that RUNS. Verified:
+    # exit 0 and "hi" on stdout, arm64 and x86_64.
+    ("gimple_runtime_print_runs",
      "def main():\n"
      "    mojo_print(\"hi\")\n"
      "    return 0\n",
-     "refuse:is an entry point of the gimple backend's C runtime", None),
+     0, None),
     # The one that is NOT answerable by linking the library, which is why the
     # refusal says more than "no library here". `mojo_list_len` takes a
     # `MojoList *` — a heap box the gimple runtime owns — where a list on this
```

**WHY** — the case is a claim about the old target, not about the new one, and a
test that is false about the compiler is worse than no test.

**BLOCKS** — `make gate`. Until it lands, `formal-run` is 338/2.

**NOT AFFECTED, and worth recording so nobody re-checks it:** the other new
failure in that file, `limit_ellipsis_function_body`, is **pre-existing**. Its
message comes from `formal/model.py:5262`, which is outside this agent's diff
(`git diff -U0 formal/model.py` hunks stop at 4580). It fails identically before
and after.

**ALSO WORTH ADDING to this file, if the integrator prefers one home for the
runtime-link cases:** `test_formal_runtime_link.py` (new, 108 checks) is the
thorough file, and it is a separate file on purpose — it needs `otool` and
builds ~20 images across both architectures, which `test_formal_run.py`'s
compile-and-run loop should not absorb.

## [5] → integrator · `tools/suite.py` · register the new test

**WHAT** — register `test_formal_runtime_link.py`. Suggested placement: the
`proofs` bucket, beside `formal-link-accounting` (it is the same layer, and it is
asserted *without* Lean, so it does not need `deps=['prooflib']` — it can go in
`check` if the integrator would rather have it in the everyday subset, at a cost
of ~20 image builds; I would put it in `proofs`).

```python
# driver: cmd        memclass: small       deps: —
# the gimple runtime's C library on a formal link line
Test("formal-runtime-link", "python3", "test_formal_runtime_link.py",
     buckets=("proofs",), memclass="small"),
```

**WHY** — an unregistered test file does not run, which is the difference between
a claim and a check.

**BLOCKS** — nothing; it is a one-line registration, and it is the integrator's
by the operating contract either way.

## [5] → next round · `build_stdlib_dylib.py` + `build_config.py` · 45 entry points

Not urgent and not owned this round — both files are on the deliberate
unowned list, and the mechanism works without it. Filed because the number it
moves is measured and the cost is known.

**WHAT** — a `runtime_dylib` variant that also compiles the OPTIONAL units the
caller names and passes their `-l` flags to `_dylink` (currently it links
`runtime_units(arch, None)`, which is the core + coroutine + async only).

**WHY** — 45 of the 207 word-shaped entry points are declared in
`runtime/fire_sqlite3.h` / `fire_ssl.h` / `fire_zlib.h` / `fire_ncurses.h` and
defined in units the dylib does not link, so a formal image refuses them for a
reason ("this image's link line does not define X") that a link line could fix.
The other 6 (`mojo_python_*`) must **stay** refused: `fire_python.c` is
`#if USE_PYTHON 0` stubs by design and FORMAL.md phase 0 decided it is
deliberately never linked, so that a missing python runtime stays a loud link
error instead of becoming a silent NULL.

**BLOCKS** — nothing of this agent's. The 5 sweep-corpus files
(`test_sqlite3*.mojo`) that name a `mojo_*` call would move; the other 588 would
not, because none of them calls the core runtime either (measured).

**THE PART THAT IS NOT MECHANICAL**, and the reason this is a note rather than a
patch: `fire_ssl.c` does not compile on a host without OpenSSL headers. Measured
here: `runtime/fire_ssl.c:2:10: fatal error: openssl/ssl.h: No such file or
directory`, which is why `test_runtime_dylib.py` already skips ssl. A formal
build naming a `mojo_ssl_*` call would fail with a **C compiler error** instead
of a Mojo refusal, which is a worse diagnostic than the one it replaces. The
mechanism has to be "link the units that compile, refuse the rest, and say which
unit was missing" — and the refusal already has a branch for exactly that
(`gimple_runtime_refusal`'s word case, now worded for it).
