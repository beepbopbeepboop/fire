#!/usr/bin/env python3
"""Launch a command fully detached: new session, no inherited descriptors.

`nohup cmd &` is not enough here. The shell this repository is driven from
terminates a command that exceeds its timeout, and it takes the whole process
group with it; nohup only ignores SIGHUP, so a detached `make gate` still died
mid-run, twice, at the point the runner was doing real work. That wasted two
full gate attempts and — worse — each one was invalid, because the source kept
moving underneath it.

The fix is a new session (os.setsid), so the process is not in the launching
shell's process group at all, plus every inherited descriptor closed or
redirected to /dev/null, so nothing holds the launching shell's pipes open.
"""
import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: detach.py <logfile> <cmd> [args...]", file=sys.stderr)
        return 2
    logfile, cmd = sys.argv[1], sys.argv[2:]
    null = os.open(os.devnull, os.O_RDONLY)
    out = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    pid = os.fork()
    if pid:
        # Parent: report the child and get out without touching its fds.
        print(pid)
        os.close(null)
        os.close(out)
        return 0
    # Child: new session, so no shell can signal us by process group.
    os.setsid()
    os.dup2(null, 0)
    os.dup2(out, 1)
    os.dup2(out, 2)
    for fd in range(3, 256):
        try:
            if fd not in (out, null):
                os.close(fd)
        except OSError:
            pass
    os.execvp(cmd[0], cmd)
    os._exit(127)


if __name__ == "__main__":
    sys.exit(main())
