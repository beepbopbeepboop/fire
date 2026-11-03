
import fcntl
import os

def main() -> int:
    fd = os.open("/tmp/x", os.O_RDWR | os.O_CREAT, 0o644)
    r = fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)
    return r
