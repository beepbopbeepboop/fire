# Pinning regression for FORMAL: a return-less call's value prints `None`.
#
# Direction (b): a function that falls off its end (or whose every `return` is
# `None` or a call to one that answers `None`) is statically `None`, and `None`
# is the absence of a word on this path — so the ONLY honest rendering is the
# four characters, written into the format string at build time. Before the fix
# the callee's epilogue left whatever its last instruction wrote in the return
# register and the image printed `0` (or `(null)` through `printf`'s `%s`).
#
# All the positions where the value becomes TEXT, on BOTH architectures: the
# direct call, a local bound to the call, one `return` hop out, and printf's
# text conversion. The variants are in one program because each is one line of
# the same build, so the whole file is two builds rather than eight.

SOURCE = (
    "def g(a, b):\n"
    "    w = 1\n"
    "\n"
    "def h(a, b):\n"
    "    return g(a, b)\n"
    "\n"
    "def main()->Int32:\n"
    "    print(g(1, 2))\n"
    "    v = g(1, 2)\n"
    "    print(v)\n"
    "    print(h(1, 2))\n"
    "    printf(\"[%s]\", g(1, 2))\n"
    "    return 0\n")

WANT = "None\nNone\nNone\n[None]"


def test_return_less_call_returns_none():
    import subprocess, sys, os
    src = ".tmp/reg/probe2.mojo"
    os.makedirs(".tmp/reg", exist_ok=True)
    with open(src, "w") as f:
        f.write(SOURCE)
    for backend in ("arm64", "x86_64"):
        out = subprocess.run(
            [sys.executable, "fire.py", "build", "--formal", "--no-prove",
             f"--backend={backend}", "-o", ".tmp/reg/y2", src],
            capture_output=True, text=True)
        assert out.returncode == 0, (
            f"--backend={backend} build failed: "
            f"{(out.stderr or out.stdout)[:500]}")
        run = subprocess.run([".tmp/reg/y2"], capture_output=True, text=True)
        assert run.stdout == WANT, (
            f"--backend={backend}: expected {WANT!r}, got: {run.stdout!r}")


if __name__ == "__main__":
    test_return_less_call_returns_none()
    print("PASS")
