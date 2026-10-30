#!/usr/bin/env python3
"""The feeder's stop indicator: a `STOP: <reason>` line in a bug doc is the only thing that keeps it off the queue.

    python3 tools/test_swarm_feed.py

Uses a temporary tree (C.MAIN is pointed at it), so the live registry and bugs/ are never read."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import swarm as S


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    return cond


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        C.MAIN = tmp
        os.makedirs(os.path.join(tmp, "bugs"))
        open(os.path.join(tmp, "bugs", "plain.md"), "w").write("# A bug\n\n## Status\n\nOPEN.\n")
        open(os.path.join(tmp, "bugs", "stopped.md"), "w").write(
            "# A bug\n\nSTOP: needs the owner's decision on FORMAL scope\n\n## Status\n")
        ok &= check("a doc without a STOP line has no stop", S.stop_reason("plain") is None)
        ok &= check("the STOP line gives its reason", S.stop_reason("stopped") ==
                    "needs the owner's decision on FORMAL scope")
        ok &= check("a missing doc has no stop", S.stop_reason("nope") is None)
        open(os.path.join(tmp, "bugs", "mention.md"), "w").write(
            "# A bug\n\nThe word STOP: appears mid-line, and the note says do not stop.\n")
        ok &= check("STOP: mid-line is not a stop marker", S.stop_reason("mention") is None)
    print("all passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
