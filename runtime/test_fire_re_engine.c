#include <stdio.h>
#include "fire_re_engine.inc"
/* usage: test_fire_re_engine MODE FLAGS PATTERN TEXT  ->  prints "None" or "start end g1 g2 ..." (spans), or "ERR" */
int main(int argc, char **argv) {
    int mode = atoi(argv[1]); int flags = atoi(argv[2]);
    FreProg *pg = fre_compile(argv[3], flags);
    if (pg->ncode < 0) { printf("ERR\n"); return 0; }
    const char *t = argv[4]; int64_t n = (int64_t)strlen(t);
    int64_t caps[64];
    if (!fre_exec(pg, t, n, 0, n, mode, caps)) { printf("None\n"); return 0; }
    for (int i = 0; i <= pg->ngroups; i++) printf("%s%lld,%lld", i ? " " : "", (long long)caps[2*i], (long long)caps[2*i+1]);
    printf("\n"); return 0;
}
