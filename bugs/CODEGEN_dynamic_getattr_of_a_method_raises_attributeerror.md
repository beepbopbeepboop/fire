# CODEGEN: a dynamic getattr of a method raises AttributeError even though the static path works

**State: OPEN, unfixed.** Found 2026-10-19, right after the "bound method of an
untyped receiver" fix (fixed, doc removed with its fix). That fix taught the
generated `_mojo_getattr_<Struct>` dispatch to answer a bound method for a
*statically named* method access. Going through the runtime `getattr()` builtin
still misses, so the two spellings of the same lookup disagree.

## What I ran and what I saw

    class C:
        def tag(self) -> str:
            return "T"

    def main():
        c = C()
        t = getattr(c, "tag")
        print(t())

    main()

CPython prints `T` and exits 0.

Both compiled and interpreted runs raise:

    AttributeError: tag

The static spellings of the very same lookup all work, in both paths:

    def main():
        c = C()
        print(c.tag())    # T
        f = c.tag
        print(f())        # T

## Why

`c.tag` is resolved at compile time and now reaches a method arm in the
reflection dispatch. `getattr(c, "tag")` carries a runtime string and is
lowered onto the runtime getattr, which appears to consult only the field
table (and whatever the compile-time arm table it does not share). The fix
should make the runtime getattr answer a bound method for a method name the
same way the compile-time arm does, so there is one answer, not two.

## Reproduce

    python3 fire.py --jit that-file.mojo
    python3 fire.py run   that-file.mojo

## Not fixing here

- `setattr` of a method, and instance-attribute shadowing of a method via
  `getattr` on a *subclass* instance, both untested here.
- This is adjacent to, and separate from, the overload-as-a-value link error
  filed alongside it: that one fails to build, this one builds and raises.
