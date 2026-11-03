
import fcntl

def main() -> int:
    r = fcntl.flock(0, fcntl.LOCK_EX() | fcntl.LOCK_NB())
    return r
