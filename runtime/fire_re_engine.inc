/* fire_re_engine.inc -- a small backtracking regular-expression engine that
 * compiles a pattern STRING at run time (the compile-time engine in
 * fire_runtime.c, ReNode / mojo_regex_search, only runs programs the compiler
 * emitted ahead of time from literal patterns).
 *
 * Included by fire_runtime.c; depends on libc only, so it is testable alone
 * (see test_fire_re_engine.c).  Syntax is Python's `re`:
 *   literals, escapes (\n \t \\ \. ...), \d \D \w \W \s \S, \b \B, \A \Z,
 *   . [..] [^..] with ranges / escapes / classes, ( ) (?: ) (?P<n> ) (?P=n)
 *   (?i) (?s) (?m) (?x)-less flag groups (?i: ) (?-i: ), (?= ) (?! ) (?<= )
 *   (?<! ) (?> ), alternation, * + ? {m} {m,} {m,n} and lazy forms, ^ $,
 *   backreferences \1..\9.
 * Text is UTF-8: `.`, sets and literals work on code points.
 *
 * The matcher is a backtracking VM over a flat instruction array.  Lookaround
 * and atomic groups run their body as a nested match. */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define FRE_I 2
#define FRE_M 8
#define FRE_S 16

enum {
    FO_CHAR, FO_ANY, FO_SET, FO_SPLIT, FO_JMP, FO_SAVE, FO_BOL, FO_EOL,
    FO_BOS, FO_EOS, FO_EOSNL, FO_WORDB, FO_NWORDB, FO_LOOK, FO_ATOMIC,
    FO_BACKREF, FO_RESET, FO_LOOPCHK, FO_SUBEND, FO_MATCH
};

typedef struct { int op; int x, y, z; } FreIns;
typedef struct { int lo, hi; } FreRange;
typedef struct {
    int neg;
    uint8_t ascii[32];      /* bitmap for code points < 256 */
    FreRange *r; int nr, cap;   /* ranges for code points >= 128 (also in bitmap if < 256) */
} FreSet;

typedef struct {
    FreIns *code; int ncode, capcode;
    FreSet *sets; int nsets, capsets;
    int ngroups;            /* number of capturing groups (group 0 excluded) */
    int nregs;              /* loop-check registers */
    int flags;
    char **gnames;          /* gnames[i] for group i (1-based) or NULL */
    char err[96];
} FreProg;

/* ---------- AST ---------- */
enum { FN_EMPTY, FN_CHAR, FN_ANY, FN_SET, FN_CAT, FN_ALT, FN_REP, FN_GROUP,
       FN_LOOK, FN_ATOMIC, FN_ASSERT, FN_BACKREF };
typedef struct FreNode {
    int t;
    int a, b;               /* char / set idx / min,max / group idx / assert kind */
    int greedy;
    int flags;              /* case-insensitive etc. captured at parse time */
    int neg, behind;
    struct FreNode *l, *r, *next;   /* CAT: l then r ; ALT: l | r ; unary: l */
} FreNode;

typedef struct {
    const char *p; const char *end;
    int flags; FreProg *pg; int err;
    char **names; int nnames;
} FreParser;

static FreNode *fre_node(FreParser *ps, int t) {
    FreNode *n = (FreNode *)calloc(1, sizeof *n);
    n->t = t; n->flags = ps->flags; n->greedy = 1;
    return n;
}
static void fre_free_node(FreNode *n) {
    if (!n) return;
    fre_free_node(n->l); fre_free_node(n->r);
    free(n);
}
static int fre_fail(FreParser *ps, const char *m) {
    if (!ps->err) { ps->err = 1; strncpy(ps->pg->err, m, sizeof ps->pg->err - 1); }
    return 0;
}

static int fre_utf8_dec(const char *s, const char *end, int *len) {
    unsigned char c = (unsigned char)*s;
    if (c < 0x80 || s + 1 > end) { *len = 1; return c; }
    if ((c & 0xE0) == 0xC0 && s + 2 <= end) { *len = 2; return ((c & 0x1F) << 6) | (s[1] & 0x3F); }
    if ((c & 0xF0) == 0xE0 && s + 3 <= end) { *len = 3; return ((c & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); }
    if ((c & 0xF8) == 0xF0 && s + 4 <= end) { *len = 4; return ((c & 0x07) << 18) | ((s[1] & 0x3F) << 12) | ((s[2] & 0x3F) << 6) | (s[3] & 0x3F); }
    *len = 1; return c;
}

static void fre_set_add(FreSet *s, int lo, int hi) {
    for (int c = lo; c <= hi && c < 256; c++) s->ascii[c >> 3] |= (uint8_t)(1 << (c & 7));
    if (hi >= 128) {
        if (s->nr == s->cap) { s->cap = s->cap ? s->cap * 2 : 4; s->r = (FreRange *)realloc(s->r, s->cap * sizeof *s->r); }
        s->r[s->nr].lo = lo < 128 ? 128 : lo; s->r[s->nr].hi = hi; s->nr++;
    }
}
static int fre_set_has(const FreSet *s, int c) {
    int in = 0;
    if (c < 256) in = (s->ascii[c >> 3] >> (c & 7)) & 1;
    if (!in && c >= 128) for (int i = 0; i < s->nr; i++) if (c >= s->r[i].lo && c <= s->r[i].hi) { in = 1; break; }
    return in != s->neg;
}
static int fre_is_word(int c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c >= 128; }
static int fre_lower(int c) { return (c >= 'A' && c <= 'Z') ? c + 32 : c; }

static void fre_class_add(FreSet *s, int cls) {
    switch (cls) {
    case 'd': fre_set_add(s, '0', '9'); break;
    case 'w': fre_set_add(s, '0', '9'); fre_set_add(s, 'a', 'z'); fre_set_add(s, 'A', 'Z'); fre_set_add(s, '_', '_'); fre_set_add(s, 128, 0x10FFFF); break;
    case 's': fre_set_add(s, ' ', ' '); fre_set_add(s, '\t', '\r'); break;
    case 'D': fre_set_add(s, 0, '0' - 1); fre_set_add(s, '9' + 1, 0x10FFFF); break;
    case 'W': { fre_set_add(s, 0, '0' - 1); fre_set_add(s, '9' + 1, 'A' - 1); fre_set_add(s, 'Z' + 1, '_' - 1); fre_set_add(s, '_' + 1, 'a' - 1); fre_set_add(s, 'z' + 1, 127); break; }
    case 'S': fre_set_add(s, 0, 8); fre_set_add(s, 14, 31); fre_set_add(s, 33, 0x10FFFF); break;
    }
}

static int fre_new_set(FreParser *ps) {
    FreProg *pg = ps->pg;
    if (pg->nsets == pg->capsets) { pg->capsets = pg->capsets ? pg->capsets * 2 : 8; pg->sets = (FreSet *)realloc(pg->sets, pg->capsets * sizeof *pg->sets); }
    memset(&pg->sets[pg->nsets], 0, sizeof(FreSet));
    return pg->nsets++;
}

static int fre_escape_char(int c) {
    switch (c) { case 'n': return '\n'; case 't': return '\t'; case 'r': return '\r'; case 'f': return '\f';
                 case 'v': return '\v'; case 'a': return '\a'; case '0': return 0; default: return c; }
}

static FreNode *fre_parse_alt(FreParser *ps);

static FreNode *fre_parse_set(FreParser *ps) {
    /* after '[' */
    int si = fre_new_set(ps);
    FreNode *n = fre_node(ps, FN_SET); n->a = si;
    int first = 1;
    if (ps->p < ps->end && *ps->p == '^') { ps->pg->sets[si].neg = 1; ps->p++; }
    while (1) {
        if (ps->p >= ps->end) { fre_fail(ps, "unterminated character set"); return n; }
        if (*ps->p == ']' && !first) { ps->p++; break; }
        first = 0;
        int len, lo;
        if (*ps->p == '\\' && ps->p + 1 < ps->end) {
            char e = ps->p[1];
            if (strchr("dwsDWS", e)) { fre_class_add(&ps->pg->sets[si], e); ps->p += 2; continue; }
            lo = fre_escape_char(e); ps->p += 2;
        } else { lo = fre_utf8_dec(ps->p, ps->end, &len); ps->p += len; }
        int hi = lo;
        if (ps->p + 1 < ps->end && *ps->p == '-' && ps->p[1] != ']') {
            ps->p++;
            if (*ps->p == '\\' && ps->p + 1 < ps->end) { hi = fre_escape_char(ps->p[1]); ps->p += 2; }
            else { hi = fre_utf8_dec(ps->p, ps->end, &len); ps->p += len; }
            if (hi < lo) { fre_fail(ps, "bad character range"); return n; }
        }
        fre_set_add(&ps->pg->sets[si], lo, hi);
        if (ps->flags & FRE_I) {
            for (int c = lo; c <= hi && c < 128; c++) {
                if (c >= 'a' && c <= 'z') fre_set_add(&ps->pg->sets[si], c - 32, c - 32);
                if (c >= 'A' && c <= 'Z') fre_set_add(&ps->pg->sets[si], c + 32, c + 32);
            }
        }
    }
    return n;
}

static int fre_parse_int(FreParser *ps, int *out) {
    if (ps->p >= ps->end || *ps->p < '0' || *ps->p > '9') return 0;
    int v = 0;
    while (ps->p < ps->end && *ps->p >= '0' && *ps->p <= '9') { v = v * 10 + (*ps->p - '0'); ps->p++; if (v > 100000) v = 100000; }
    *out = v; return 1;
}

static int fre_flag_bit(char c) { return c == 'i' ? FRE_I : c == 'm' ? FRE_M : c == 's' ? FRE_S : 0; }

static FreNode *fre_parse_atom(FreParser *ps) {
    char c = *ps->p++;
    FreNode *n;
    switch (c) {
    case '.': return fre_node(ps, FN_ANY);
    case '^': n = fre_node(ps, FN_ASSERT); n->a = (ps->flags & FRE_M) ? FO_BOL : FO_BOS; return n;
    case '$': n = fre_node(ps, FN_ASSERT); n->a = (ps->flags & FRE_M) ? FO_EOL : FO_EOSNL; return n;
    case '[': return fre_parse_set(ps);
    case '(': {
        int cap = 1, look = 0, neg = 0, behind = 0, atomic = 0, saved_flags = ps->flags, scoped = 0;
        char *name = NULL;
        if (ps->p < ps->end && *ps->p == '?') {
            ps->p++;
            cap = 0;
            if (ps->p >= ps->end) { fre_fail(ps, "unexpected end of pattern"); return fre_node(ps, FN_EMPTY); }
            char k = *ps->p;
            if (k == ':') { ps->p++; }
            else if (k == '=') { ps->p++; look = 1; }
            else if (k == '!') { ps->p++; look = 1; neg = 1; }
            else if (k == '>') { ps->p++; atomic = 1; }
            else if (k == '<' && ps->p + 1 < ps->end && (ps->p[1] == '=' || ps->p[1] == '!')) { look = 1; behind = 1; neg = ps->p[1] == '!'; ps->p += 2; }
            else if (k == 'P' && ps->p + 1 < ps->end && ps->p[1] == '<') {
                ps->p += 2; const char *s = ps->p;
                while (ps->p < ps->end && *ps->p != '>') ps->p++;
                if (ps->p >= ps->end) { fre_fail(ps, "missing >"); return fre_node(ps, FN_EMPTY); }
                name = (char *)malloc((size_t)(ps->p - s) + 1); memcpy(name, s, (size_t)(ps->p - s)); name[ps->p - s] = 0;
                ps->p++; cap = 1;
            } else if (k == 'P' && ps->p + 1 < ps->end && ps->p[1] == '=') {
                ps->p += 2; const char *s = ps->p;
                while (ps->p < ps->end && *ps->p != ')') ps->p++;
                size_t ln = (size_t)(ps->p - s); ps->p++;
                n = fre_node(ps, FN_BACKREF); n->a = -1;
                for (int i = 1; i <= ps->pg->ngroups; i++)
                    if (ps->pg->gnames[i] && strlen(ps->pg->gnames[i]) == ln && !memcmp(ps->pg->gnames[i], s, ln)) n->a = i;
                if (n->a < 0) fre_fail(ps, "unknown group name");
                return n;
            } else if (k == '#') {
                while (ps->p < ps->end && *ps->p != ')') ps->p++;
                if (ps->p < ps->end) ps->p++;
                return fre_node(ps, FN_EMPTY);
            } else {
                /* flags: (?ims) or (?ims-ims:...) */
                int on = 0, off = 0, minus = 0;
                while (ps->p < ps->end && (strchr("imsaxLu-", *ps->p))) {
                    if (*ps->p == '-') minus = 1; else if (minus) off |= fre_flag_bit(*ps->p); else on |= fre_flag_bit(*ps->p);
                    ps->p++;
                }
                if (ps->p < ps->end && *ps->p == ')') { ps->p++; ps->flags = (ps->flags | on) & ~off; return fre_node(ps, FN_EMPTY); }
                if (ps->p < ps->end && *ps->p == ':') { ps->p++; ps->flags = (ps->flags | on) & ~off; scoped = 1; }
                else { fre_fail(ps, "unknown extension"); return fre_node(ps, FN_EMPTY); }
            }
        }
        int gi = 0;
        if (cap) { gi = ++ps->pg->ngroups;
            ps->pg->gnames = (char **)realloc(ps->pg->gnames, (size_t)(gi + 1) * sizeof(char *));
            ps->pg->gnames[gi] = name; }
        FreNode *body = fre_parse_alt(ps);
        if (ps->p >= ps->end || *ps->p != ')') { fre_fail(ps, "missing )"); }
        else ps->p++;
        (void)scoped;
        ps->flags = saved_flags;
        if (look) { n = fre_node(ps, FN_LOOK); n->l = body; n->neg = neg; n->behind = behind; return n; }
        if (atomic) { n = fre_node(ps, FN_ATOMIC); n->l = body; return n; }
        if (cap) { n = fre_node(ps, FN_GROUP); n->a = gi; n->l = body; return n; }
        return body;
    }
    case '\\': {
        if (ps->p >= ps->end) { fre_fail(ps, "bad escape (end of pattern)"); return fre_node(ps, FN_EMPTY); }
        char e = *ps->p++;
        if (strchr("dwsDWS", e)) { int si = fre_new_set(ps); fre_class_add(&ps->pg->sets[si], e); n = fre_node(ps, FN_SET); n->a = si; return n; }
        if (e == 'b' || e == 'B') { n = fre_node(ps, FN_ASSERT); n->a = e == 'b' ? FO_WORDB : FO_NWORDB; return n; }
        if (e == 'A') { n = fre_node(ps, FN_ASSERT); n->a = FO_BOS; return n; }
        if (e == 'Z' || e == 'z') { n = fre_node(ps, FN_ASSERT); n->a = FO_EOS; return n; }
        if (e >= '1' && e <= '9') { n = fre_node(ps, FN_BACKREF); n->a = e - '0'; return n; }
        n = fre_node(ps, FN_CHAR); n->a = fre_escape_char(e); return n;
    }
    default: {
        n = fre_node(ps, FN_CHAR);
        if ((unsigned char)c >= 0x80) { int len; ps->p--; n->a = fre_utf8_dec(ps->p, ps->end, &len); ps->p += len; }
        else n->a = (unsigned char)c;
        return n;
    }
    }
}

static FreNode *fre_parse_rep(FreParser *ps) {
    if (ps->p >= ps->end) return fre_node(ps, FN_EMPTY);
    FreNode *a = fre_parse_atom(ps);
    while (!ps->err && ps->p < ps->end) {
        int mn, mx; char c = *ps->p;
        if (c == '*') { mn = 0; mx = -1; ps->p++; }
        else if (c == '+') { mn = 1; mx = -1; ps->p++; }
        else if (c == '?') { mn = 0; mx = 1; ps->p++; }
        else if (c == '{') {
            const char *save = ps->p; ps->p++;
            int lo = 0, hi = -1, have = fre_parse_int(ps, &lo);
            if (ps->p < ps->end && *ps->p == ',') { ps->p++; if (!fre_parse_int(ps, &hi)) hi = -1; if (!have) lo = 0; }
            else hi = lo;
            if (!(have || hi >= 0) || ps->p >= ps->end || *ps->p != '}') { ps->p = save; break; }
            ps->p++; mn = lo; mx = hi;
        } else break;
        FreNode *r = fre_node(ps, FN_REP); r->a = mn; r->b = mx; r->l = a;
        if (ps->p < ps->end && *ps->p == '?') { r->greedy = 0; ps->p++; }
        else if (ps->p < ps->end && *ps->p == '+') { /* possessive */ ps->p++; FreNode *at = fre_node(ps, FN_ATOMIC); at->l = r; a = at; continue; }
        a = r;
    }
    return a;
}

static FreNode *fre_parse_cat(FreParser *ps) {
    FreNode *head = NULL;
    while (!ps->err && ps->p < ps->end && *ps->p != '|' && *ps->p != ')') {
        FreNode *x = fre_parse_rep(ps);
        if (!head) head = x;
        else { FreNode *c = fre_node(ps, FN_CAT); c->l = head; c->r = x; head = c; }
    }
    return head ? head : fre_node(ps, FN_EMPTY);
}

static FreNode *fre_parse_alt(FreParser *ps) {
    FreNode *l = fre_parse_cat(ps);
    while (!ps->err && ps->p < ps->end && *ps->p == '|') {
        ps->p++;
        FreNode *r = fre_parse_cat(ps);
        FreNode *a = fre_node(ps, FN_ALT); a->l = l; a->r = r; l = a;
    }
    return l;
}

/* ---------- code emission ---------- */
static int fre_emit(FreProg *pg, int op, int x, int y, int z) {
    if (pg->ncode == pg->capcode) { pg->capcode = pg->capcode ? pg->capcode * 2 : 64; pg->code = (FreIns *)realloc(pg->code, (size_t)pg->capcode * sizeof(FreIns)); }
    pg->code[pg->ncode].op = op; pg->code[pg->ncode].x = x; pg->code[pg->ncode].y = y; pg->code[pg->ncode].z = z;
    return pg->ncode++;
}

static int fre_can_be_empty(const FreNode *n) {
    if (!n) return 1;
    switch (n->t) {
    case FN_CHAR: case FN_ANY: case FN_SET: return 0;
    case FN_CAT: return fre_can_be_empty(n->l) && fre_can_be_empty(n->r);
    case FN_ALT: return fre_can_be_empty(n->l) || fre_can_be_empty(n->r);
    case FN_REP: return n->a == 0 || fre_can_be_empty(n->l);
    case FN_GROUP: case FN_ATOMIC: return fre_can_be_empty(n->l);
    default: return 1;
    }
}

static void fre_gen(FreParser *ps, const FreNode *n);

static void fre_gen_rep(FreParser *ps, const FreNode *n) {
    FreProg *pg = ps->pg;
    int mn = n->a, mx = n->b;
    if (mn > 1000 || mx > 1000) { fre_fail(ps, "repeat count too large"); return; }
    for (int i = 0; i < mn; i++) fre_gen(ps, n->l);
    if (mx == -1) {
        /* L: split body, out ; body ; jmp L */
        int empty = fre_can_be_empty(n->l);
        int reg = empty ? pg->nregs++ : -1;
        int L = fre_emit(pg, FO_SPLIT, 0, 0, 0);
        int body = pg->ncode;
        if (empty) fre_emit(pg, FO_LOOPCHK, reg, 0, 1);       /* remember pos */
        fre_gen(ps, n->l);
        if (empty) fre_emit(pg, FO_LOOPCHK, reg, 0, 2);       /* fail if no progress */
        fre_emit(pg, FO_JMP, L, 0, 0);
        int out = pg->ncode;
        if (n->greedy) { pg->code[L].x = body; pg->code[L].y = out; }
        else { pg->code[L].x = out; pg->code[L].y = body; }
    } else {
        /* (max-min) optional copies, nested: x? */
        int splits[1001]; int ns = 0;
        for (int i = mn; i < mx; i++) {
            int S = fre_emit(pg, FO_SPLIT, 0, 0, 0);
            splits[ns++] = S;
            int body = pg->ncode;
            pg->code[S].x = n->greedy ? body : -1; pg->code[S].y = n->greedy ? -1 : body;
            fre_gen(ps, n->l);
        }
        int out = pg->ncode;
        for (int i = 0; i < ns; i++) { if (n->greedy) pg->code[splits[i]].y = out; else pg->code[splits[i]].x = out; }
    }
}

static void fre_gen(FreParser *ps, const FreNode *n) {
    FreProg *pg = ps->pg;
    if (ps->err || !n) return;
    switch (n->t) {
    case FN_EMPTY: break;
    case FN_CHAR: fre_emit(pg, FO_CHAR, n->a, (n->flags & FRE_I) ? 1 : 0, 0); break;
    case FN_ANY: fre_emit(pg, FO_ANY, (n->flags & FRE_S) ? 1 : 0, 0, 0); break;
    case FN_SET: fre_emit(pg, FO_SET, n->a, 0, 0); break;
    case FN_CAT: fre_gen(ps, n->l); fre_gen(ps, n->r); break;
    case FN_ALT: {
        int S = fre_emit(pg, FO_SPLIT, 0, 0, 0);
        pg->code[S].x = pg->ncode;
        fre_gen(ps, n->l);
        int J = fre_emit(pg, FO_JMP, 0, 0, 0);
        pg->code[S].y = pg->ncode;
        fre_gen(ps, n->r);
        pg->code[J].x = pg->ncode;
        break; }
    case FN_REP: fre_gen_rep(ps, n); break;
    case FN_GROUP:
        fre_emit(pg, FO_SAVE, 2 * n->a, 0, 0);
        fre_gen(ps, n->l);
        fre_emit(pg, FO_SAVE, 2 * n->a + 1, 0, 0);
        break;
    case FN_ASSERT: fre_emit(pg, n->a, 0, 0, 0); break;
    case FN_BACKREF: fre_emit(pg, FO_BACKREF, n->a, (n->flags & FRE_I) ? 1 : 0, 0); break;
    case FN_LOOK: case FN_ATOMIC: {
        int I = fre_emit(pg, n->t == FN_LOOK ? FO_LOOK : FO_ATOMIC, 0, 0, 0);
        pg->code[I].z = n->t == FN_LOOK ? ((n->neg ? 1 : 0) | (n->behind ? 2 : 0)) : 0;
        pg->code[I].x = pg->ncode;
        if (n->t == FN_LOOK && n->behind) {
            /* fixed-width lookbehind: emit body, matcher tries every start <= pos */
        }
        fre_gen(ps, n->l);
        fre_emit(pg, FO_SUBEND, 0, 0, 0);
        pg->code[I].y = pg->ncode;
        break; }
    }
}

static FreProg *fre_compile(const char *pat, int flags) {
    FreProg *pg = (FreProg *)calloc(1, sizeof *pg);
    pg->flags = flags;
    pg->gnames = (char **)calloc(1, sizeof(char *));
    FreParser ps; memset(&ps, 0, sizeof ps);
    ps.p = pat; ps.end = pat + strlen(pat); ps.flags = flags; ps.pg = pg;
    FreNode *root = fre_parse_alt(&ps);
    if (!ps.err && ps.p < ps.end) fre_fail(&ps, "unbalanced parenthesis");
    if (!ps.err) {
        fre_emit(pg, FO_SAVE, 0, 0, 0);
        fre_gen(&ps, root);
        fre_emit(pg, FO_SAVE, 1, 0, 0);
        fre_emit(pg, FO_MATCH, 0, 0, 0);
    }
    fre_free_node(root);
    if (ps.err) { pg->ncode = -1; }
    return pg;
}

static void fre_free(FreProg *pg) {
    if (!pg) return;
    for (int i = 0; i < pg->nsets; i++) free(pg->sets[i].r);
    for (int i = 1; i <= pg->ngroups; i++) free(pg->gnames[i]);
    free(pg->gnames); free(pg->sets); free(pg->code); free(pg);
}

/* ---------- matching ---------- */
typedef struct { int kind, a; int64_t b; } FreStk;   /* kind 0: choice (pc a, pos b); 1: restore cap a to b; 2: restore reg a to b */
typedef struct {
    const FreProg *pg; const char *s; int64_t n;
    int64_t *caps; int64_t *regs;
    FreStk *stk; int64_t sp, cap;
    int64_t steps; int need_end;
} FreVm;

static int fre_push(FreVm *vm, int kind, int a, int64_t b) {
    if (vm->sp == vm->cap) { vm->cap = vm->cap ? vm->cap * 2 : 256; vm->stk = (FreStk *)realloc(vm->stk, (size_t)vm->cap * sizeof(FreStk)); }
    vm->stk[vm->sp].kind = kind; vm->stk[vm->sp].a = a; vm->stk[vm->sp].b = b; vm->sp++;
    return 1;
}

static int fre_wordat(const FreVm *vm, int64_t pos) {
    if (pos < 0 || pos >= vm->n) return 0;
    return fre_is_word((unsigned char)vm->s[pos]);
}

/* run from pc at pos until FO_MATCH / FO_SUBEND; returns end position or -1.
 * `base` is the stack height this run owns. */
static int64_t fre_run(FreVm *vm, int pc, int64_t pos) {
    int64_t base = vm->sp;
    const FreIns *code = vm->pg->code;
    for (;;) {
        const FreIns *in = &code[pc];
        int ok = 1;
        if (++vm->steps > 200000000) return -1;
        switch (in->op) {
        case FO_CHAR: {
            if (pos >= vm->n) { ok = 0; break; }
            int len; int c = fre_utf8_dec(vm->s + pos, vm->s + vm->n, &len);
            if (c == in->x || (in->y && fre_lower(c) == fre_lower(in->x))) { pos += len; pc++; } else ok = 0;
            break; }
        case FO_ANY: {
            if (pos >= vm->n) { ok = 0; break; }
            if (!in->x && vm->s[pos] == '\n') { ok = 0; break; }
            int len; fre_utf8_dec(vm->s + pos, vm->s + vm->n, &len);
            pos += len; pc++; break; }
        case FO_SET: {
            if (pos >= vm->n) { ok = 0; break; }
            int len; int c = fre_utf8_dec(vm->s + pos, vm->s + vm->n, &len);
            if (fre_set_has(&vm->pg->sets[in->x], c)) { pos += len; pc++; } else ok = 0;
            break; }
        case FO_SPLIT:
            if (in->y >= 0) fre_push(vm, 0, in->y, pos);
            pc = in->x; break;
        case FO_JMP: pc = in->x; break;
        case FO_SAVE:
            fre_push(vm, 1, in->x, vm->caps[in->x]);
            vm->caps[in->x] = pos; pc++; break;
        case FO_BOL: if (pos == 0 || vm->s[pos - 1] == '\n') pc++; else ok = 0; break;
        case FO_EOL: if (pos == vm->n || vm->s[pos] == '\n') pc++; else ok = 0; break;
        case FO_BOS: if (pos == 0) pc++; else ok = 0; break;
        case FO_EOS: if (pos == vm->n) pc++; else ok = 0; break;
        case FO_EOSNL: if (pos == vm->n || (pos == vm->n - 1 && vm->s[pos] == '\n')) pc++; else ok = 0; break;
        case FO_WORDB: case FO_NWORDB: {
            int a = fre_wordat(vm, pos - 1), b = fre_wordat(vm, pos);
            if ((a != b) == (in->op == FO_WORDB)) pc++; else ok = 0;
            break; }
        case FO_BACKREF: {
            int64_t st = vm->caps[2 * in->x], en = vm->caps[2 * in->x + 1];
            if (st < 0 || en < 0) { ok = 0; break; }
            int64_t ln = en - st;
            if (pos + ln > vm->n) { ok = 0; break; }
            int eq = 1;
            for (int64_t i = 0; i < ln && eq; i++) {
                int a = (unsigned char)vm->s[st + i], b = (unsigned char)vm->s[pos + i];
                if (a != b && !(in->y && fre_lower(a) == fre_lower(b))) eq = 0;
            }
            if (eq) { pos += ln; pc++; } else ok = 0;
            break; }
        case FO_LOOPCHK:
            if (in->z == 1) { fre_push(vm, 2, in->x, vm->regs[in->x]); vm->regs[in->x] = pos; pc++; }
            else { if (vm->regs[in->x] == pos) ok = 0; else pc++; }
            break;
        case FO_LOOK: {
            int neg = in->z & 1, behind = in->z & 2;
            int64_t save_sp = vm->sp; int64_t r = -1;
            if (behind) {
                for (int64_t st = pos; st >= 0 && r < 0; st--) {
                    int64_t e = fre_run(vm, in->x, st);
                    if (e == pos) r = e;
                    else if (e >= 0) { /* body matched but ended elsewhere: keep trying shorter */ }
                    vm->sp = save_sp;
                }
            } else {
                r = fre_run(vm, in->x, pos);
                vm->sp = save_sp;
            }
            if ((r >= 0) != (neg != 0)) pc = in->y; else ok = 0;
            break; }
        case FO_ATOMIC: {
            int64_t save_sp = vm->sp;
            int64_t r = fre_run(vm, in->x, pos);
            if (r >= 0) { vm->sp = save_sp; pos = r; pc = in->y; } else ok = 0;
            break; }
        case FO_SUBEND: return pos;
        case FO_MATCH: if (vm->need_end && pos != vm->n) { ok = 0; break; } return pos;
        default: ok = 0;
        }
        if (!ok) {
            for (;;) {
                if (vm->sp <= base) return -1;
                FreStk *e = &vm->stk[--vm->sp];
                if (e->kind == 1) vm->caps[e->a] = e->b;
                else if (e->kind == 2) vm->regs[e->a] = e->b;
                else { pc = e->a; pos = e->b; break; }
            }
        }
    }
}

/* try one start position; fills caps (2*(ngroups+1)). returns 1 on match.
 * mode: 0 prefix-match at start, 2 full match (must end at `endpos`). */
static int fre_exec_at(const FreProg *pg, const char *s, int64_t n, int64_t start, int64_t endpos, int full, int64_t *caps) {
    FreVm vm; memset(&vm, 0, sizeof vm);
    vm.pg = pg; vm.s = s; vm.n = endpos < n ? endpos : n;
    int nc = 2 * (pg->ngroups + 1);
    vm.caps = caps; for (int i = 0; i < nc; i++) caps[i] = -1;
    int64_t *regs = pg->nregs ? (int64_t *)calloc((size_t)pg->nregs, sizeof(int64_t)) : NULL;
    vm.regs = regs;
    vm.need_end = full;
    int found = fre_run(&vm, 0, start) >= 0;
    free(regs); free(vm.stk);
    return found;
}

/* search from `pos`; mode 0=match(at pos) 1=search 2=fullmatch.  Returns 1 and fills caps. */
static int fre_exec(const FreProg *pg, const char *s, int64_t n, int64_t pos, int64_t endpos, int mode, int64_t *caps) {
    if (pos < 0) pos = 0;
    if (endpos > n) endpos = n;
    if (mode == 1) {
        for (int64_t st = pos; st <= endpos; st++) {
            if (fre_exec_at(pg, s, n, st, endpos, 0, caps)) return 1;
            if (st < endpos) { int len; fre_utf8_dec(s + st, s + endpos, &len); st += len - 1; }
        }
        return 0;
    }
    return fre_exec_at(pg, s, n, pos, endpos, mode == 2, caps);
}

/* ---------- bytes variants ---------- */
static int fre_byte_dec(const char *s, const char *end, int *len) {
    (void)end;
    *len = 1;
    return (unsigned char)*s;
}

static FreProg *fre_compile_bytes(const char *pat, int len, int flags) {
    FreProg *pg = (FreProg *)calloc(1, sizeof *pg);
    pg->flags = flags;
    pg->gnames = (char **)calloc(1, sizeof(char *));
    FreParser ps; memset(&ps, 0, sizeof ps);
    ps.p = pat; ps.end = pat + len; ps.flags = flags; ps.pg = pg;
    FreNode *root = fre_parse_alt(&ps);
    if (!ps.err && ps.p < ps.end) fre_fail(&ps, "unbalanced parenthesis");
    if (!ps.err) {
        fre_emit(pg, FO_SAVE, 0, 0, 0);
        fre_gen(&ps, root);
        fre_emit(pg, FO_SAVE, 1, 0, 0);
        fre_emit(pg, FO_MATCH, 0, 0, 0);
    }
    fre_free_node(root);
    if (ps.err) { pg->ncode = -1; }
    return pg;
}

static int fre_exec_bytes(const FreProg *pg, const char *s, int64_t n, int64_t pos, int64_t endpos, int mode, int64_t *caps) {
    if (pos < 0) pos = 0;
    if (endpos > n) endpos = n;
    if (mode == 1) {
        for (int64_t st = pos; st <= endpos; st++) {
            if (fre_exec_at(pg, s, n, st, endpos, 0, caps)) return 1;
            if (st < endpos) { int len; fre_byte_dec(s + st, s + endpos, &len); st += len - 1; }
        }
        return 0;
    }
    return fre_exec_at(pg, s, n, pos, endpos, mode == 2, caps);
}
