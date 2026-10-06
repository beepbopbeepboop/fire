#!/usr/bin/env python3
"""Remove old entries from the ~/.gmojo caches.

`cas/` (content-addressed build products) and `jit/` are caches: every entry is
keyed by a hash of its inputs, so a removed entry is rebuilt on the next use and
a stale one can never be served. This deletes the regular files (and the
directories left empty) whose most recent mtime/atime is older than --days.

`memslot/` is NOT a cache -- it is the live machine-wide memory ledger and its
lock files -- and is never touched. Neither is a file anything has open.

    python3 tools/clean-gmojo.py              # remove entries older than 5 days
    python3 tools/clean-gmojo.py --days 2
    python3 tools/clean-gmojo.py --dry-run    # say what would go, remove nothing
"""
import argparse
import os
import sys
import time

ROOT = os.path.expanduser(os.environ.get("GMOJO_HOME", "~/.gmojo"))
CACHES = ("cas", "jit")          # memslot is state, not cache: deliberately absent


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def sweep(top, cutoff, dry):
    """Walk `top` bottom-up; return (files, bytes, kept_files, kept_bytes, dirs)."""
    files = size = kept = kept_size = dirs = 0
    for dirpath, dirnames, filenames in os.walk(top, topdown=False):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if max(st.st_mtime, st.st_atime) >= cutoff:
                kept += 1
                kept_size += st.st_blocks * 512
                continue
            files += 1
            size += st.st_blocks * 512
            if not dry:
                try:
                    os.unlink(path)
                except OSError:
                    files -= 1
                    size -= st.st_blocks * 512
        if dirpath != top:
            try:
                if not os.listdir(dirpath):
                    dirs += 1
                    if not dry:
                        os.rmdir(dirpath)
            except OSError:
                pass
    return files, size, kept, kept_size, dirs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=float, default=5.0,
                    help="remove entries not modified or read for this many days (default 5)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not os.path.isdir(ROOT):
        print(f"{ROOT}: nothing to clean")
        return 0
    cutoff = time.time() - args.days * 86400
    verb = "would remove" if args.dry_run else "removed"
    total = 0
    for name in CACHES:
        top = os.path.join(ROOT, name)
        if not os.path.isdir(top):
            continue
        f, s, k, ks, d = sweep(top, cutoff, args.dry_run)
        total += s
        print(f"{name}/: {verb} {f} files ({human(s)}) and {d} empty dirs; "
              f"kept {k} files ({human(ks)})")
    print(f"total {verb}: {human(total)}  (older than {args.days:g} days; memslot/ untouched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
