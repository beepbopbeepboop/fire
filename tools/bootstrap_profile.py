#!/usr/bin/env python3
"""Profile bootstrap stages to identify memory/time hotspots.

This tool profiles bootstrap builds to identify hotspots for resource usage.
It can run with heapprof for memory profiling or use system time for timing.
"""
import argparse
import os
import subprocess
import sys
import time


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def build_heapprof():
    """Build heapprof dylib if needed."""
    build_dir = os.path.join(REPO, 'build')
    os.makedirs(build_dir, exist_ok=True)
    dylib = os.path.join(build_dir, 'heapprof.dylib')
    src = os.path.join(HERE, 'heapprof.c')
    if os.path.exists(dylib) and os.path.getmtime(dylib) >= os.path.getmtime(src):
        return dylib
    cmd = ['cc', '-O2', '-dynamiclib', '-o', dylib, src]
    result = subprocess.run(cmd, cwd=REPO)
    if result.returncode != 0:
        raise RuntimeError(f'Failed to build heapprof: {result.returncode}')
    return dylib


def profile_bootstrap_stages(stages=None, use_heapprof=False, interval=None):
    """Profile bootstrap stages to identify hotspots."""
    if stages is None:
        stages = ['bootstrap-stage1-dumps', 'bootstrap-stage2-dumps', 'bootstrap-stage3-dumps']
    
    results = []
    for stage in stages:
        print(f'Profiling {stage}...', file=sys.stderr)
        start = time.time()
        env = os.environ.copy()
        
        if use_heapprof:
            try:
                dylib = build_heapprof()
                out_prefix = os.path.join(REPO, '.tmp', f'bootstrap_hotspot_{stage}')
                os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
                env['DYLD_INSERT_LIBRARIES'] = dylib
                env['HEAPPROF_OUT'] = out_prefix
                if interval:
                    env['HEAPPROF_INTERVAL'] = str(interval)
            except Exception as e:
                print(f'Warning: heapprof not available: {e}', file=sys.stderr)
                use_heapprof = False
        
        # Use suite to run the stage
        cmd = [sys.executable, 'tools/suite.py', stage]
        result = subprocess.run(cmd, cwd=REPO, env=env)
        elapsed = time.time() - start
        
        results.append({
            'stage': stage,
            'time': elapsed,
            'returncode': result.returncode
        })
        print(f'{stage}: {elapsed:.1f}s (rc={result.returncode})', file=sys.stderr)
    
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stages', nargs='*', help='Bootstrap stages to profile')
    ap.add_argument('--heapprof', action='store_true', help='Use heapprof for memory profiling')
    ap.add_argument('--interval', type=int, help='Heapprof sampling interval')
    ap.add_argument('--report', action='store_true', help='Generate hotspot report')
    opts = ap.parse_args()
    
    results = profile_bootstrap_stages(opts.stages, opts.heapprof, opts.interval)
    
    print('\n=== Bootstrap Hotspot Profile ===')
    for r in results:
        print(f"{r['stage']}: {r['time']:.1f}s")
    print('=== End Profile ===')
    
    return 0 if all(r['returncode'] == 0 for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
