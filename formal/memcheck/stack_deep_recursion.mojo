# Recursion on the path whose stack floor guard is supposed to stop it
# (`formal/model.py`'s STACK_TRAP_STATUS, exit 2).  The memcheck question is not
# "does it trap" -- that is the differential corpus's -- but whether every frame
# it does push is one the poison painted: the guard compares sp against a floor
# computed from the entry sp, so a guard off by a frame either traps early (this
# row) or not at all.
#
# 40, and the number is not arbitrary.  EVERY arm64 function reserves 128 KB of
# frame scratch (`formal/model.py::ARM64_CONTAINER_BUDGET`, so that a list blob
# can live in the frame), and the main thread's stack is 8 MB, so the whole
# recursion budget on that backend is about 60 frames before the guard fires --
# measured: `depth(3000)` traps with exit 2 on both architectures and prints
# nothing.  x86-64 sizes its frame to what the function needs
# (`subq $0x4110, %rsp`) and has thousands of frames.  That asymmetry is a
# designed consequence of the container budget rather than a defect, and this
# row is where the number it implies is written down.
def depth(n: Int) -> Int:
    if n <= 0:
        return 0
    return 1 + depth(n - 1)

def main(n: Int) -> Int:
    printf("%d\n", depth(40))
    return 0
