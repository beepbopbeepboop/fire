# `test_the_lock_names_the_holder` takes the MACHINE-WIDE sweep lock, so it is red whenever a sibling worker is sweeping

**Status:** open. Found 2026-10-02 while merging the formal6 batch; not this
merge's to fix, and not fixed.

## What I ran

    export PATH=/opt/homebrew/bin:$PATH
    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep.py

and, to decide whether the merge had caused it, the same file out of a
`git archive master` tree (`.tmp/master_tree`, master = 4384e756):

    cd .tmp/master_tree && python3 .../tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep.py

## What I saw

Both runs, on master and on the merge branch, end with the same single failure
and the same test:

    FAIL: test_the_lock_names_the_holder (__main__.TestSweepLock.test_the_lock_names_the_holder)
    ...
      File "test_formal_sweep.py", line 1638, in test_the_lock_names_the_holder
        self.assertTrue(mod._claim_arch("arm64", ["a.py"]))
    AssertionError: False is not true

    Ran 81 tests   (merge branch; 79 on master — the branch adds the admitted tier's two)
    Ran 79 tests   (master tree)

The same call succeeds when nothing else is sweeping. Traced:

    CLAIM arm64 cas= /Users/mrs/.gmojo/cas path= /Users/mrs/.gmojo/cas/formal-sweep-arm64.lock
      -> False

and at that moment:

    $ ps aux | grep -c '[f]ormal_sweep'
    45
    $ cat ~/.gmojo/cas/formal-sweep-arm64.lock
    10830
    /Users/mrs/.../std/__init__.mojo /Users/mrs/.../std/_gpu/__init__.mojo ...

— a sibling worker's sweep, holding the lock it is supposed to hold.

## What I expected

The test's own `_with_cas(cas_dir, ...)` redirects `cas.CAS_DIR` at a temp dir,
but it is called with `lambda: None` and RESTORES `CAS_DIR` before the claim:

    with tempfile.TemporaryDirectory() as cas_dir:
        self._with_cas(cas_dir, lambda: None)          # redirected, then restored
        self.assertTrue(mod._claim_arch("arm64", ["a.py"]))   # DEFAULT cas dir

so the assertion is about `~/.gmojo/cas/formal-sweep-arm64.lock` — a lock whose
whole purpose is to stop two sweeps sharing a machine — rather than about the
lock file's CONTENTS, which is what the rest of the test checks. A test that
reads "the lock names the holder" is asserting a property of the file; taking
the machine's real lock is a side effect of it, and on a machine with other
workers it is a red that means "someone else is working", not "the lock is
wrong".

The neighbouring case is right and is the model: `test_the_lock_is_released_
when_the_holder_dies` claims inside the redirected cas dir, so it is free.

## The exact next step

In `test_the_lock_names_the_holder`, keep the claim INSIDE the redirect — pass
the body to `_with_cas` rather than calling it with a no-op lambda:

    with tempfile.TemporaryDirectory() as cas_dir:
        body = {}

        def claim():
            self.assertTrue(mod._claim_arch("arm64", ["a.py"]))
            with open(mod.sweep_lock_path("arm64")) as f:
                body["text"] = f.read()

        self._with_cas(cas_dir, claim)
        self.assertIn(str(os.getpid()), body["text"])
        self.assertIn("a.py", body["text"])

Then run it while a sweep holds the real lock; it must stay green, because it is
now talking about its own file. While there, worth deciding whether any other
test in `TestSweepLock` reaches outside its temp `CAS_DIR` — the class has one
more case and I did not read it for the same property.

Not run here: this file is 81 unit cases and the two runs above are all of it.
No gate, no sweep.
