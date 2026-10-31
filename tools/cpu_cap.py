#!/usr/bin/env python3
"""A CPU-time ceiling for worker processes, which ratchets down as measured runs come in.

    python3 tools/cpu_cap.py wrap --name NAME [--hours H] -- CMD ARGS...   # run CMD under the cap, record its CPU
    python3 tools/cpu_cap.py show                                          # the default cap now
    python3 tools/cpu_cap.py ratchet                                       # lower the default from the records

The cap is RLIMIT_CPU: a process (and every child it starts, since limits are inherited) that
has used its CPU budget gets SIGXCPU, and SIGKILL one minute later. A worker that is stuck in a
loop therefore stops itself, instead of running for days.

Policy (tools/cpu_policy.json): the default starts at 2 hours. A task may ask for more, up to the
ceiling (7 days), with --hours. `ratchet` only ever LOWERS the default: it is set to twice the 90th
percentile of recent measured runs, never below the floor (10 minutes), and only once there are at
least FLOOR_RUNS measured runs. Records live in .git/control/cpu/, one JSON file per run."""
import argparse, glob, json, os, resource, signal, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.dirname(HERE)
POLICY = os.path.join(HERE, "cpu_policy.json")
RECDIR = os.path.join(MAIN, ".git", "control", "cpu")
FLOOR_RUNS = 5
GRACE_S = 60


def policy():
    p = json.load(open(POLICY))
    return p["default_hours"], p["floor_hours"], p["ceiling_hours"]


def wrap(name, hours, argv):
    default, _floor, ceiling = policy()
    h = min(hours if hours is not None else default, ceiling)
    cap = int(h * 3600)
    os.makedirs(RECDIR, exist_ok=True)

    def limit():
        resource.setrlimit(resource.RLIMIT_CPU, (cap, cap + GRACE_S))

    p = subprocess.Popen(argv, preexec_fn=limit)
    rc = p.wait()
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = ru.ru_utime + ru.ru_stime
    rec = {"name": name, "cpu_s": round(cpu, 1), "cap_s": cap, "exit": rc,
           "capped": rc in (-signal.SIGXCPU, -signal.SIGKILL, 128 + signal.SIGXCPU, 128 + signal.SIGKILL),
           "at": time.strftime("%F %T")}
    json.dump(rec, open(os.path.join(RECDIR, "%s-%d.json" % (name[:60], int(time.time() * 1000))), "w"), indent=1)
    print("cpu_cap: %s used %.0f s of a %d s cap (exit %s%s)" % (
        name, cpu, cap, rc, ", CAPPED" if rec["capped"] else ""), file=sys.stderr)
    return rc if rc >= 0 else 128 - rc


def show():
    default, floor, ceiling = policy()
    print("default cap %.2f h (floor %.2f h, ceiling %.0f h)" % (default, floor, ceiling))


def ratchet():
    default, floor, ceiling = policy()
    runs = []
    for f in glob.glob(os.path.join(RECDIR, "*.json")):
        try:
            r = json.load(open(f))
            if not r["capped"]:              # a capped run is not a measurement of what the work needs
                runs.append(r["cpu_s"])
        except (OSError, ValueError, KeyError):
            pass
    if len(runs) < FLOOR_RUNS:
        print("ratchet: %d measured runs, need %d; default stays %.2f h" % (len(runs), FLOOR_RUNS, default))
        return default
    runs.sort()
    p90 = runs[min(len(runs) - 1, int(0.9 * len(runs)))]
    new = max(floor, min(default, 2 * p90 / 3600.0))   # only down
    if new < default - 1e-9:
        p = json.load(open(POLICY))
        p["default_hours"] = round(new, 3)
        json.dump(p, open(POLICY, "w"), indent=2)
        print("ratchet: default lowered %.2f h -> %.2f h (p90 of %d runs = %.0f s)" % (default, new, len(runs), p90))
    else:
        print("ratchet: default stays %.2f h (p90 of %d runs = %.0f s)" % (default, len(runs), p90))
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wrap")
    w.add_argument("--name", required=True)
    w.add_argument("--hours", type=float, default=None)
    w.add_argument("rest", nargs=argparse.REMAINDER)
    sub.add_parser("show")
    sub.add_parser("ratchet")
    a = ap.parse_args()
    if a.cmd == "wrap":
        argv = a.rest[1:] if a.rest and a.rest[0] == "--" else a.rest
        sys.exit(wrap(a.name, a.hours, argv))
    if a.cmd == "show":
        show()
    else:
        ratchet()


if __name__ == "__main__":
    main()
