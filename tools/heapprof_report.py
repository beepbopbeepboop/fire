#!/usr/bin/env python3
"""Report a tools/heapprof.c snapshot: which allocation sites hold the live bytes.

    heapprof_report.py SNAPSHOT.txt [--top N] [--depth D] [--by leaf|stack|caller] [--skip REGEX]

Frames are symbolised with `atos` against the main image recorded in the snapshot.  Runtime
allocator frames (mojo_str_cat, mojo_list_append, ...) are usually not the interesting frame:
the interesting one is the compiled-Python function that called them, so `--by caller` (the
default) attributes each stack to its first frame outside the runtime (`--skip`).
"""
import argparse, collections, re, subprocess, sys


def load(path):
    images, stacks, meta, crash = [], [], "", []
    for line in open(path):
        if line.startswith("#"):
            meta = line.strip()
        elif line.startswith("IMAGE"):
            _, idx, base, name = line.rstrip("\n").split(" ", 3)
            images.append((int(base, 16), name))
        elif line.startswith("CRASH"):
            crash = [int(x, 16) for x in line.split()[1:]]
        elif line.startswith("S "):
            f = line.split()
            stacks.append((int(f[1]), int(f[2]), int(f[3]), int(f[4]), [int(x, 16) for x in f[5:]]))
    return meta, images, stacks, crash


def symbolise(images, addrs):
    """addr -> 'function' using atos per image (frames sit after the image base)."""
    images = sorted(images)
    out = {}
    by_img = collections.defaultdict(list)
    for a in addrs:
        img = None
        for base, name in images:
            if a >= base:
                img = (base, name)
        by_img[img].append(a)
    for img, al in by_img.items():
        if img is None:
            for a in al: out[a] = hex(a)
            continue
        base, name = img
        try:
            r = subprocess.run(["atos", "-o", name, "-l", hex(base)] + [hex(a - 1) for a in al],
                               capture_output=True, text=True, timeout=600)
            lines = r.stdout.splitlines()
        except Exception:
            lines = []
        for a, ln in zip(al, lines + [""] * len(al)):
            out[a] = ln.split(" (in ")[0] if ln and not ln.startswith("0x") else hex(a)
    return out


def gb(x): return "%.2f GB" % (x / 2**30) if x >= 2**30 else "%.1f MB" % (x / 2**20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--by", choices=["leaf", "stack", "caller"], default="caller")
    ap.add_argument("--skip", default=r"^(mojo_|_mojo_|_str_|_list_|_dict_|_set_|_ptr|_slot|malloc|calloc|realloc|strdup|hp_|_dict|_set|_list)")
    ap.add_argument("--total", action="store_true", help="rank by bytes allocated over the run instead of live bytes")
    a = ap.parse_args()
    meta, images, stacks, crash = load(a.snapshot)
    print(meta)
    stacks = [s for s in stacks if (s[2] if a.total else s[0]) > 0]
    addrs = sorted({pc for s in stacks for pc in s[4][:max(a.depth, 12)]} | set(crash))
    sym = symbolise(images, addrs)
    skip = re.compile(a.skip)
    agg = collections.defaultdict(lambda: [0, 0, 0, 0])
    for lb, lc, tb, tc, pcs in stacks:
        names = [sym.get(pc, hex(pc)) for pc in pcs]
        if a.by == "leaf":
            key = names[0] if names else "?"
        elif a.by == "caller":
            key = next((n for n in names if not skip.search(n)), names[0] if names else "?")
            key = "%s  <- %s" % (key, names[0]) if names and names[0] != key else key
        else:
            key = "\n      ".join(names[:a.depth])
        g = agg[key]; g[0] += lb; g[1] += lc; g[2] += tb; g[3] += tc
    idx = 2 if a.total else 0
    tot = sum(g[idx] for g in agg.values()) or 1
    if crash:
        print("CRASH stack (pc first):")
        for pc in crash:
            print("   ", sym.get(pc, hex(pc)))
        print()
    print("total %s across %d sites\n" % (gb(tot), len(agg)))
    for key, g in sorted(agg.items(), key=lambda kv: -kv[1][idx])[:a.top]:
        print("%10s %5.1f%%  live %s in ~%d blocks | allocated over run %s in ~%d\n      %s" % (
            gb(g[idx]), 100.0 * g[idx] / tot, gb(g[0]), g[1], gb(g[2]), g[3], key))


if __name__ == "__main__":
    main()
