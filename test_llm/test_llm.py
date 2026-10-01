"""A ~1M-parameter character-level language model in pure Python.

No numpy, no torch, no external libraries -- just ``math`` and ``struct``.
Nothing here uses autograd: forward, backward, the optimizer and inference are
all written out by hand so every gradient is visible.

    Config.full()  the ~1M parameter model
    Config.tiny()  a small model used by the tests

The interesting layer is the attention.  There is no KV cache that grows with
the context.  Each layer keeps exactly one fixed-size ``d x d`` matrix of
state:

    S_t = alpha_t * S_{t-1} + k_t (x) v_t          alpha_t in (0, 1)
    o_t = S_t^T q_t

alpha_t is a data-dependent gate (sigmoid of a learned projection), so the
model picks per token how fast to overwrite what it knows and how fast to
forget.  Everything the layer needs in order to answer the next query lives
in S, so a token costs O(d^2) time and O(d^2) state whether it is token 5 or
token 5000.  ``TestAttentionMath.test_recurrent_matches_the_non_recurrent_form``
is the check on that, and ``linear_attention_parallel`` is the same math
written in cumulative-product form -- a completely separate derivation -- so
the recurrence can be checked against it.

Run it::

    python3 test_llm.py                 # train the 1M model, print samples
    python3 test_llm.py --steps 200     # train longer
    python3 test_llm.py --tiny --steps 300
    python3 -m unittest test_llm -v
"""

import struct
import sys
import time
import unittest
from io import StringIO
from math import cos as _cos
from math import exp, log, sqrt

# --------------------------------------------------------------------------
# bf16
#
# bfloat16 is fp32 with the mantissa cut from 23 bits to 7, so a bf16 value is
# just an fp32 value whose low 16 mantissa bits are zero.  Rounding is
# round-half-to-even, which is what add-then-mask below does.
# --------------------------------------------------------------------------

FP32_MAX = 3.4028234663852886e38
INF = float("inf")


def bf16(x):
    """Round a Python float to the nearest bfloat16 value."""
    if x != x or x == INF or x == -INF:
        return x
    if x > FP32_MAX:
        return INF
    if x < -FP32_MAX:
        return -INF
    bits = struct.unpack("<I", struct.pack("<f", x))[0]
    bits = (bits + 0x7FFF + ((bits >> 16) & 1)) & 0xFFFF0000
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def bf16_all(xs):
    return list(map(bf16, xs))


def is_bf16(x):
    return bf16(x) == x


def sigmoid(x):
    if x >= 0.0:
        return 1.0 / (1.0 + exp(-x))
    e = exp(x)
    return e / (1.0 + e)


def dot(a, b):
    """The inner product, as a plain loop.

    `sum(map(mul, a, b))` is the idiomatic form and it is what this used to
    be, but `from operator import mul` is a name this compiler cannot yet
    resolve, and a genexp is a generator function it refuses outright. An
    explicit loop is one level lower, portable, and (measured) no slower.
    """
    total = 0.0
    for i in range(len(a)):
        total = total + a[i] * b[i]
    return total


def dot_(a, b):
    return dot(a, b)


def zeros(rows, cols):
    """A rows x cols zero matrix, as nested lists."""
    out = [None] * rows
    for i in range(rows):
        out[i] = [0.0] * cols
    return out


def matvec_t(s, q):
    """o = S^T q, i.e. o[i] = sum_j s[j][i] * q[j] -- the attention read."""
    d = len(q)
    out = [0.0] * d
    for j in range(d):
        qj = q[j]
        row = s[j]
        for i in range(d):
            out[i] = out[i] + qj * row[i]
    return out


def add_scaled(dst, src, k):
    """dst[i] += k * src[i], in place."""
    for i in range(len(dst)):
        dst[i] = dst[i] + k * src[i]
    return dst


def add(a, b):
    out = [0.0] * len(a)
    for i in range(len(a)):
        out[i] = a[i] + b[i]
    return out


def mul_scalar(a, k):
    out = [0.0] * len(a)
    for i in range(len(a)):
        out[i] = a[i] * k
    return out


# --------------------------------------------------------------------------
# parameters and optimizer
# --------------------------------------------------------------------------


class Tensor:
    """A flat fp32 parameter block stored row-major, with its own gradients.

    ``data`` is the master copy.  ``quantize()`` runs after every optimizer
    step and rounds the master copy to bf16, which is what a real mixed
    precision setup does: the update is computed in fp32, the model only ever
    stores the bf16 shadow of it.
    """

    registry = []

    def __init__(self, name, rows: int, cols: int, decay=True):
        self.name = name
        self.rows = rows
        self.cols = cols
        self.n = rows * cols
        self.decay = decay
        self.data = [0.0] * self.n
        self.grad = [0.0] * self.n
        self.pgrad = [0.0] * self.n
        self.m = [0.0] * self.n
        self.v = [0.0] * self.n
        Tensor.registry.append(self)

    def fill(self, rng, scale, base=None):
        if base is None:
            self.data = [0.0] * self.n
        for i in range(self.n):
            self.data[i] = base if base is not None else (rng.random() * 2.0 - 1.0) * scale
        return self

    def row(self, i):
        base = i * self.cols
        return self.data[base:base + self.cols]

    def grad_row(self, i):
        base = i * self.cols
        return self.grad[base:base + self.cols]

    def add_grad_row(self, i, g):
        base = i * self.cols
        gr = self.grad
        row = [0.0] * self.cols
        for j in range(self.cols):
            row[j] = gr[base + j] + g[j]
        gr[base:base + self.cols] = row

    def zero_grad(self):
        self.grad = [0.0] * self.n
        self.pgrad = [0.0] * self.n

    def fold_pgrad(self):
        """Move the scalar-parameter gradients into the main grad list."""
        pg = self.pgrad
        for i in range(self.n):
            if pg[i] != 0.0:
                self.grad[i] += pg[i]
                pg[i] = 0.0

    def quantize(self):
        self.data = bf16_all(self.data)

    def all_bf16(self):
        for x in self.data:
            if not is_bf16(x):
                return False
        return True

    def numel(self):
        return self.n


def reset_registry():
    del Tensor.registry[:]


class Rng:
    """Deterministic LCG, so runs are reproducible without importing random."""

    def __init__(self, seed):
        self.s = (seed * 2862933555777941757 + 3037000493) & 0xFFFFFFFFFFFFFFFF

    def random(self):
        self.s = (self.s * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return ((self.s >> 11) & 0xFFFFFFFF) * (1.0 / 4294967296.0)


class AdamW:
    """Adam with decoupled weight decay, in fp32, over the Tensor registry."""

    def __init__(self, lr=3e-3, b1=0.9, b2=0.95, eps=1e-8, wd=0.01, clip=1.0):
        self.lr = lr
        self.b1 = b1
        self.b2 = b2
        self.eps = eps
        self.wd = wd
        self.clip = clip
        self.t = 0

    def grad_norm(self):
        total = 0.0
        for p in Tensor.registry:
            for g in p.grad:
                total += g * g
        return sqrt(total)

    def step(self):
        self.t += 1
        scale = 1.0
        if self.clip > 0.0:
            gn = self.grad_norm()
            if gn > self.clip:
                scale = self.clip / (gn + 1e-6)
        bc1 = 1.0 - self.b1 ** self.t
        bc2 = 1.0 - self.b2 ** self.t
        for p in Tensor.registry:
            m = p.m
            v = p.v
            g = p.grad
            d = p.data
            wd = self.wd * p.decay
            for i in range(p.n):
                gi = g[i] * scale
                m[i] = self.b1 * m[i] + (1.0 - self.b1) * gi
                v[i] = self.b2 * v[i] + (1.0 - self.b2) * gi * gi
                d[i] = d[i] - self.lr * ((m[i] / bc1) / (sqrt(v[i] / bc2) + self.eps) + wd * d[i])
        for p in Tensor.registry:
            p.quantize()

    def zero_grad(self):
        for p in Tensor.registry:
            p.zero_grad()


# --------------------------------------------------------------------------
# layers
# --------------------------------------------------------------------------


class Linear:
    """y = W x + b, with the backward pass written out."""

    def __init__(self, name, n_in: int, n_out: int, rng, bias=True, decay=True):
        scale = 1.0 / sqrt(n_in)
        self.w = Tensor(name + ".w", n_out, n_in, decay).fill(rng, scale)
        self.b = None
        if bias:
            self.b = Tensor(name + ".b", 1, n_out, False).fill(rng, 0.0, base=0.0)
        self.n_in = n_in
        self.n_out = n_out

    def numel(self):
        n = self.w.numel()
        if self.b is not None:
            n = n + self.b.numel()
        return n

    def forward(self, x):
        out = [0.0] * self.n_out
        for i in range(self.n_out):
            out[i] = dot(self.w.row(i), x)
        if self.b is not None:
            b = self.b.data
            for i in range(self.n_out):
                out[i] = out[i] + b[i]
        return out

    def backward(self, g, x):
        """Accumulate parameter grads; return the gradient wrt x."""
        gx = [0.0] * self.n_in
        scaled = [0.0] * self.n_in
        for i in range(self.n_out):
            gi = g[i]
            if gi == 0.0:
                continue
            for j in range(self.n_in):
                scaled[j] = gi * x[j]
            self.w.add_grad_row(i, scaled)
            if self.b is not None:
                self.b.pgrad[i] += gi
            row = self.w.row(i)
            for j in range(self.n_in):
                gx[j] = gx[j] + gi * row[j]
        return gx


class RMSNorm:
    """y = g * x / rms(x).  Cache is returned because a sequence runs this
    once per token and the backward pass needs the per-token xhat."""

    def __init__(self, name, d: int, eps=1e-5):
        self.g = Tensor(name + ".g", 1, d, False).fill(Rng(7), 0.0, base=1.0)
        self.eps = eps
        self.d = d

    def numel(self):
        return self.g.numel()

    def forward(self, x):
        n = len(x)
        r = 1.0 / sqrt(dot(x, x) / n + self.eps)
        xhat = [0.0] * n
        for i in range(n):
            xhat[i] = x[i] * r
        g = self.g.data
        out = [0.0] * n
        for i in range(n):
            out[i] = xhat[i] * g[i]
        return out, (xhat, r)

    def backward(self, gy, cache):
        xhat, r = cache
        n = self.d
        g = self.g.data
        gxh = [0.0] * n
        for i in range(n):
            gxh[i] = gy[i] * g[i]
        dp = dot_(gxh, xhat) / n
        for i in range(n):
            self.g.pgrad[i] = self.g.pgrad[i] + gy[i] * xhat[i]
        out = [0.0] * n
        for i in range(n):
            out[i] = (gxh[i] - xhat[i] * dp) * r
        return out


class GatedLinearAttention:
    """The constant-state attention layer.

    Forward carries one d x d state and caches one line per token.  Backward
    walks the sequence in reverse carrying a single d x d accumulator, which
    is what makes the training cost the same O(T d^2) as inference.
    """

    def __init__(self, name, d: int, rng):
        self.q = Linear(name + ".q", d, d, rng)
        self.k = Linear(name + ".k", d, d, rng)
        self.v = Linear(name + ".v", d, d, rng)
        self.o = Linear(name + ".o", d, d, rng)
        scale = 1.0 / sqrt(d)
        self.gate = Tensor(name + ".gate", 1, d).fill(rng, scale)
        self.d = d
        self.zero_state = zeros(d, d)

    def numel(self):
        return (self.q.numel() + self.k.numel() + self.v.numel()
                + self.o.numel() + self.gate.numel())

    def forward(self, ns, steps, s0):
        """`ns` is the whole sequence as ONE flat buffer of `steps` vectors
        of length d, i.e. step t lives at ns[t*d:(t+1)*d]. Flat rather than
        a list of per-step lists: it is the layout a GPU kernel wants (one
        contiguous allocation, strided instead of pointer-chasing), and it
        keeps the sequence one container deep everywhere."""
        d = self.d
        s = s0
        cache = []
        for step in range(steps):
            n = ns[step * d:step * d + d]
            q = self.q.forward(n)
            k = self.k.forward(n)
            v = self.v.forward(n)
            alpha = sigmoid(dot_(self.gate.data, n))
            sprev = s
            s = zeros(d, d)
            for j in range(d):
                row = [0.0] * d
                prev = sprev[j]
                kj = k[j]
                for i in range(d):
                    row[i] = alpha * prev[i] + kj * v[i]
                s[j] = row
            o = matvec_t(s, q)
            cache.append((n, q, k, v, alpha, sprev, o))
        return s, cache

    def backward(self, cache, gos):
        d = self.d
        gate = self.gate
        acc = zeros(d, d)
        gns = [None] * len(cache)
        gq = [0.0] * d
        gk = [0.0] * d
        gv = [0.0] * d
        for t in range(len(cache) - 1, -1, -1):
            n, q, k, v, alpha, sprev, o = cache[t]
            go = gos[t]
            # dS_t = dS_{t+1} (propagated) + q_t (x) go_t
            g = zeros(d, d)
            for j in range(d):
                row = [0.0] * d
                qj = q[j]
                arow = acc[j]
                for i in range(d):
                    row[i] = arow[i] + qj * go[i]
                g[j] = row
            # o[i] = sum_j S[j][i] q[j], so dq[j] = sum_i go[i] S[j][i]
            #      = alpha * sum_i go[i] S_prev[j][i] + k[j] * sum_i go[i] v[i]
            vdotgo = dot_(v, go)
            gdot = 0.0
            for j in range(d):
                gv[j] = 0.0
            for j in range(d):
                gj = g[j]
                sp = sprev[j]
                kj = k[j]
                gk[j] = dot_(gj, v)
                for i in range(d):
                    gv[i] = gv[i] + gj[i] * kj
                sdot = 0.0
                for i in range(d):
                    sdot = sdot + sp[i] * go[i]
                gq[j] = alpha * sdot + kj * vdotgo
                gd = 0.0
                for i in range(d):
                    gd = gd + gj[i] * sp[i]
                gdot = gdot + gd
            # dL/dalpha_t is the FULL Frobenius contraction over the state,
            # so the gate's own gradient only exists once every row j has
            # contributed; per-row partials are not gate gradients.
            galpha = gdot * alpha * (1.0 - alpha)
            for i in range(d):
                gate.pgrad[i] = gate.pgrad[i] + galpha * n[i]
            gn = self.k.backward(gk, n)
            gv_in = self.v.backward(gv, n)
            gq_in = self.q.backward(gq, n)
            nacc = zeros(d, d)
            for j in range(d):
                row = [0.0] * d
                gj = g[j]
                for i in range(d):
                    row[i] = alpha * gj[i]
                nacc[j] = row
            acc = nacc
            # alpha_t = sigmoid(gate . n_t), so the gate's own path back into
            # the layer input scales by the GATE vector, not by n.
            out = [0.0] * d
            for i in range(d):
                out[i] = gn[i] + gv_in[i] + gq_in[i] + galpha * gate.data[i]
            gns[t] = out
        return gns


class SwiGLU:
    """SwiGLU feed-forward: down(silu(gate(x)) * up(x))."""

    def __init__(self, name, d: int, d_ff: int, rng):
        self.gate = Linear(name + ".gate", d, d_ff, rng)
        self.up = Linear(name + ".dff", d, d_ff, rng, bias=False)
        self.down = Linear(name + ".w1", d_ff, d, rng, bias=False)

    def numel(self):
        return self.gate.numel() + self.up.numel() + self.down.numel()

    def forward(self, x):
        z1 = self.gate.forward(x)
        z2 = self.up.forward(x)
        sig = [0.0] * len(z1)
        a1 = [0.0] * len(z1)
        h = [0.0] * len(z1)
        for i in range(len(z1)):
            sig[i] = sigmoid(z1[i])
            a1[i] = z1[i] * sig[i]
            h[i] = a1[i] * z2[i]
        return h, (x, z1, z2, sig, a1, h)

    def backward(self, gy, cache):
        x, z1, z2, sig, a1, h = cache
        gh = self.down.backward(gy, h)
        gz1 = []
        gz2 = []
        for i in range(len(h)):
            g = gh[i]
            s = sig[i]
            z = z1[i]
            gz1.append(g * z2[i] * (s + z * s * (1.0 - s)))
            gz2.append(g * a1[i])
        gx = self.gate.backward(gz1, x)
        g2 = self.up.backward(gz2, x)
        return add(gx, g2)


class Block:
    """pre-norm residual block: x + attn(norm(x)), then x + mlp(norm(x))."""

    def __init__(self, name, d: int, d_ff: int, rng):
        self.norm1 = RMSNorm(name + ".norm1", d)
        self.attn = GatedLinearAttention(name + ".attn", d, rng)
        self.norm2 = RMSNorm(name + ".norm2", d)
        self.mlp = SwiGLU(name + ".mlp", d, d_ff, rng)

    def numel(self):
        return (self.norm1.numel() + self.attn.numel()
                + self.norm2.numel() + self.mlp.numel())

    def forward(self, xs, s0):
        ncache = []
        ns = [0.0] * (len(xs) * self.attn.d)
        at = 0
        for i in range(len(xs)):
            y, c = self.norm1.forward(xs[i])
            ns[at:at + self.attn.d] = y
            at = at + self.attn.d
            ncache.append(c)
        s, acache = self.attn.forward(ns, len(xs), s0)
        os_ = [None] * len(acache)
        for i in range(len(acache)):
            os_[i] = self.attn.o.forward(acache[i][6])
        xs1 = [None] * len(xs)
        for i in range(len(xs)):
            xs1[i] = add(xs[i], os_[i])
        hs = []
        hcache = []
        for x in xs1:
            y, c = self.norm2.forward(x)
            hs.append(y)
            hcache.append(c)
        mcache = []
        xs2 = []
        for i in range(len(xs1)):
            h, mc = self.mlp.forward(hs[i])
            mcache.append(mc)
            y = self.mlp.down.forward(h)
            xs2.append(add(xs1[i], y))
        return xs2, s, (ncache, acache, mcache, hcache)

    def backward(self, cache, gout):
        ncache, acache, mcache, hcache = cache
        t = len(gout)
        gxs1 = [None] * t
        for i in range(t - 1, -1, -1):
            g = self.mlp.backward(gout[i], mcache[i])
            gn = self.norm2.backward(g, hcache[i])
            gxs1[i] = add(gout[i], gn)
        gos = [None] * t
        for i in range(t):
            gos[i] = self.attn.o.backward(gxs1[i], acache[i][6])
        gns = self.attn.backward(acache, gos)
        gxs = [None] * t
        for i in range(t):
            g = self.norm1.backward(gns[i], ncache[i])
            gxs[i] = add(gxs1[i], g)
        return gxs


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------


class Config:
    def __init__(self, vocab, d_model: int = 128, n_layer: int = 6, d_ff: int = 256, eps=1e-5, seed=1):
        self.vocab = vocab
        self.d_model = d_model
        self.n_layer = n_layer
        self.d_ff = d_ff
        self.eps = eps
        self.seed = seed

    @staticmethod
    def full(vocab):
        return Config(vocab, d_model=128, n_layer=6, d_ff=256, seed=1)

    @staticmethod
    def tiny(vocab):
        return Config(vocab, d_model=16, n_layer=2, d_ff=32, seed=3)

    @staticmethod
    def micro(vocab):
        return Config(vocab, d_model=4, n_layer=1, d_ff=6, seed=5)

    def state_size(self):
        return self.n_layer * self.d_model * self.d_model


class Model:
    def __init__(self, cfg):
        self.cfg = cfg
        reset_registry()
        rng = Rng(cfg.seed)
        d = cfg.d_model
        self.emb = Tensor("emb", cfg.vocab, d, decay=False).fill(rng, 1.0 / sqrt(d))
        self.blocks = [None] * cfg.n_layer
        for i in range(cfg.n_layer):
            self.blocks[i] = Block("b%d" % i, d, cfg.d_ff, rng)
        self.norm_f = RMSNorm("norm_f", d)
        self.states = self.fresh_states()
        self.cache = None

    def num_params(self):
        # Walked STRUCTURALLY, off this model's own sublayers, rather than
        # off the class-level `Tensor.registry`. Both are the same count in
        # Python, but the registry is a container shared across functions
        # and this compiler does not carry a container's element type across
        # a function boundary (bugs/hard/CODEGEN_cross_function_container_
        # element_type.md), so the compiled build typed every element int64_t,
        # degraded `p.numel()` to a stub, and reported a pointer-sized
        # garbage number here. The structural sum has no such dependency.
        n = self.emb.numel()
        for b in self.blocks:
            n = n + b.numel()
        return n + self.norm_f.numel()

    def fresh_states(self):
        return [zeros(self.cfg.d_model, self.cfg.d_model)
                for _ in range(self.cfg.n_layer)]

    def run(self, ids, keep_cache=True, states=None):
        """Run a chunk of tokens through the stack, carrying the state in."""
        if states is None:
            states = self.states
        xs = [None] * len(ids)
        for i in range(len(ids)):
            xs[i] = self.emb.row(ids[i])[:]
        caches = []
        out_states = []
        for i, b in enumerate(self.blocks):
            xs, s, c = b.forward(xs, states[i])
            caches.append(c)
            out_states.append(s)
        hs = []
        hcache = []
        for x in xs:
            y, c = self.norm_f.forward(x)
            hs.append(y)
            hcache.append(c)
        self._hs = hs
        self._hcache = hcache
        self._ids = list(ids)
        self.states = out_states
        if keep_cache:
            self.cache = caches
        return hs, out_states

    def logits(self, ids, keep_cache=True, states=None):
        if states is None:
            states = self.fresh_states()
        hs, _ = self.run(ids, keep_cache, states)
        w = self.emb
        out = [None] * len(hs)
        for t in range(len(hs)):
            h = hs[t]
            row = [0.0] * self.cfg.vocab
            for v in range(self.cfg.vocab):
                row[v] = dot_(w.row(v), h)
            out[t] = row
        return out

    def loss_and_grads(self, ids, targets):
        """Cross entropy, and every gradient accumulated into Tensor.grad."""
        logits = self.logits(ids, keep_cache=True)
        v = self.cfg.vocab
        scale = 1.0 / len(targets)
        loss = 0.0
        dlogits = []
        for t, target in enumerate(targets):
            z = logits[t]
            m = max(z)
            s = 0.0
            p = [0.0] * v
            for j in range(v):
                e = exp(z[j] - m)
                s = s + e
                p[j] = e
            for j in range(v):
                p[j] = p[j] / s
            loss -= log(p[target])
            p[target] = p[target] - 1.0
            for j in range(v):
                p[j] = p[j] * scale
            dlogits.append(p)

        ghs = []
        for t in range(len(ids)):
            g = dlogits[t]
            h = self._hs[t]
            row = [0.0] * self.cfg.d_model
            for k in range(v):
                gk = g[k]
                if gk == 0.0:
                    continue
                wrow = self.emb.row(k)
                for j in range(self.cfg.d_model):
                    row[j] = row[j] + gk * wrow[j]
                scaled = [0.0] * self.cfg.d_model
                for j in range(self.cfg.d_model):
                    scaled[j] = gk * h[j]
                self.emb.add_grad_row(k, scaled)
            ghs.append(row)

        gxs = [None] * len(ids)
        for t in range(len(ids)):
            gxs[t] = self.norm_f.backward(ghs[t], self._hcache[t])
        for i in range(self.cfg.n_layer - 1, -1, -1):
            gxs = self.blocks[i].backward(self.cache[i], gxs)

        for t, tok in enumerate(ids):
            self.emb.add_grad_row(tok, gxs[t])
        for p in Tensor.registry:
            p.fold_pgrad()
        return loss * scale, len(targets)

    def step_token(self, tok, states):
        """One inference step.  states is the carried d x d state per layer."""
        hs, out = self.run([tok], keep_cache=False, states=states)
        h = hs[0]
        w = self.emb
        row = [0.0] * self.cfg.vocab
        for v in range(self.cfg.vocab):
            row[v] = dot_(w.row(v), h)
        return row, out


# --------------------------------------------------------------------------
# the same attention math, derived independently (used to check the recurrence)
# --------------------------------------------------------------------------


def linear_attention_parallel(qs, ks, vs, alphas):
    """S_t = alpha_t S_{t-1} + k_t (x) v_t, in cumulative-product form.

    Unrolling the recurrence:

        S_t = sum_{s<=t} (prod_{r=s+1..t} alpha_r) k_s (x) v_s
            = sum_{s<=t} (A_t / A_s) k_s (x) v_s              A_t = prod_{r<=t} alpha_r

    and since o_t[i] = sum_j S_t[j][i] q_t[j],

        o_t[i] = A_t * sum_{s<=t} (k_s . q_t) / A_s * v_s[i]

    which is a plain sum over past steps with no recurrence at all.  Every
    trace of step s into step t is the scalar ratio A_t / A_s times the
    similarity k_s . q_t, which is the reason to believe the state really is
    a summary of the context and not a cache of it.
    """
    t = len(qs)
    d = len(qs[0])
    pre = []
    a = 1.0
    for i in range(t):
        a *= alphas[i]
        pre.append(a if a > 1e-30 else 1e-30)
    out = []
    for i in range(t):
        row = []
        for c in range(d):
            acc = 0.0
            for s in range(i + 1):
                dot = 0.0
                for j in range(d):
                    dot += ks[s][j] * qs[i][j]
                acc += (dot / pre[s]) * vs[s][c]
            row.append(pre[i] * acc)
        out.append(row)
    return out


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

CORPUS = """
the model reads one character at a time and predicts the next one.
every layer keeps a fixed size state, so the cost of a token does not grow
with the length of the text that came before it. a transformer would keep a
key and a value for every earlier token and the list would grow forever.
here the state is one matrix, the gate decides how much of the old state to
keep, and the new key writes itself into the matrix. that is the whole trick.
training means running the forward pass, comparing the prediction against the
answer, and walking the computation backwards to find out which number is
responsible for the mistake. every weight gets a nudge in the direction that
would have made the mistake smaller. do that ten thousand times and the
model starts to notice that the letter after a period is usually a capital
and the letter after a space is usually the start of a word. it is not
thinking, it is counting, and counting is enough to look like thinking.
the same arithmetic runs forward at inference time with the state carried
over from one character to the next, so nothing is ever recomputed twice.
a matrix multiply is a dot product, a dot product is a sum, and a sum is the
one operation every machine on earth knows how to do quickly and in parallel.
so the model is a pile of sums, arranged in a shape that happens to be very
good at guessing the next character. that is all it is. it is still a strange
thing to have built.
"""


class Vocab:
    # `text: str` is load-bearing, not decoration. The only use of `text` in
    # this body is `set(text)`, and every container builtin (set/sorted/
    # list/tuple/enumerate) is TYPE-PRESERVING, so nothing about it says
    # "list" — it says "same element type as the argument". With no string
    # evidence anywhere, the compiler's unannotated-param inference read
    # this as a MojoList and CORPUS (a char *) was cast to MojoList * at
    # the constructor call, so `sorted(set(text))` walked a string as if it
    # were a list of pointers and died dereferencing ASCII. See
    # bugs/hard/CODEGEN_unannotated_param_container_builtin_ambiguity.md.
    def __init__(self, text: str):
        self.itos = sorted(set(text))
        self.stoi = {}
        for i, c in enumerate(self.itos):
            self.stoi[c] = i

    def __len__(self):
        return len(self.itos)

    def encode(self, text: str):
        out = []
        for c in text:
            if c not in self.stoi:
                raise KeyError("character not in vocabulary: %r" % c)
            out.append(self.stoi[c])
        return out

    def decode(self, ids):
        return "".join(self.itos[i] for i in ids)


def windows(ids, seq_len, n):
    out = []
    span = len(ids) - seq_len - 1
    for i in range(n):
        start = (i * seq_len) % span
        chunk = ids[start:start + seq_len + 1]
        out.append((chunk[:-1], chunk[1:]))
    return out


# --------------------------------------------------------------------------
# training and inference
# --------------------------------------------------------------------------


def train(model, data, steps, lr=3e-3, log_every=10,
          gen_every=0, prompt_ids=None):
    opt = AdamW(lr=lr)
    run_loss = 0.0
    runs = 0
    log = []
    t0 = time.time()
    for step in range(steps):
        inp, tgt = data[step % len(data)]
        loss, ntok = model.loss_and_grads(inp, tgt)
        opt.step()
        opt.zero_grad()
        run_loss += loss
        runs += 1
        frac = step / max(1, steps - 1)
        opt.lr = lr * (0.1 + 0.9 * 0.5 * (1.0 + _cos(3.141592653589793 * frac)))
        if (step + 1) % log_every == 0 or step == 0:
            mean = run_loss / runs
            # The log line is APPENDED to a list and written by the caller,
            # rather than written through a stream object here. This
            # compiler has no file-object model -- `sys.stdout` is a POSIX
            # fd boxed as an opaque handle, and `.write()` on a value
            # parameter carrying one cannot be resolved at all (the
            # ast_rewriter's sys.stdout.write() rule only fires on the
            # direct `sys.stdout.write(...)` shape). Returning the lines
            # also makes them assertable, which the two training tests
            # wanted a StringIO for.
            log.append("step %5d  loss %.4f  ppl %8.2f  lr %.2e  %6.1fs"
                       % (step + 1, mean, exp(min(20.0, mean)), opt.lr, time.time() - t0))
            run_loss = 0.0
            runs = 0
        if gen_every and (step + 1) % gen_every == 0 and prompt_ids is not None:
            log.append("    " + sample_text(model, VOCAB, "the ", 70, 0.8, step).replace("\n", " "))
    return log


def generate(model, prompt_ids, n_new, temperature=1.0, seed=0):
    """Sample n_new tokens, carrying the O(1) state from token to token."""
    rng = Rng(seed + 99)
    state = model.fresh_states()
    logits = None
    for tok in prompt_ids:
        logits, state = model.step_token(tok, state)
    out = []
    for _ in range(n_new):
        if temperature <= 0.0:
            best = -INF
            nxt = 0
            for i, z in enumerate(logits):
                if z > best:
                    best = z
                    nxt = i
        else:
            z = [0.0] * len(logits)
            for i in range(len(logits)):
                z[i] = logits[i] / temperature
            m = max(z)
            ex = [exp(a - m) for a in z]
            s = sum(ex)
            r = rng.random() * s
            acc = 0.0
            nxt = len(ex) - 1
            for i, e in enumerate(ex):
                acc += e
                if acc >= r:
                    nxt = i
                    break
        out.append(nxt)
        logits, state = model.step_token(nxt, state)
    return out


def sample_text(model, vocab, prompt, n_new, temperature=0.85, seed=0):
    ids = vocab.encode(prompt)
    return prompt + vocab.decode(generate(model, ids, n_new, temperature, seed))


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------


def build(vocab_size, kind="tiny"):
    if kind == "micro":
        cfg = Config.micro(vocab_size)
    elif kind == "full":
        cfg = Config.full(vocab_size)
    else:
        cfg = Config.tiny(vocab_size)
    return cfg, Model(cfg)


VOCAB = Vocab(CORPUS)


class TestBf16(unittest.TestCase):
    def test_exact_values_survive(self):
        for x in (1.0, 0.0, -2.5, 0.5, 256.0, -1.0):
            self.assertEqual(bf16(x), x)

    def test_relative_error_is_bounded(self):
        for i in range(1, 2000):
            x = i * 0.0137
            self.assertLessEqual(abs(x - bf16(x)) / abs(x), 0.0079)

    def test_every_result_is_a_fixed_point(self):
        for i in range(1000):
            self.assertTrue(is_bf16(bf16(i * 0.00311 - 0.7)))

    def test_round_half_to_even(self):
        # 1 + 2^-8 is exactly half a bf16 ulp at 1.0, and the tie has to
        # round to the EVEN neighbour (1.0), not away from zero.
        half_ulp = 1.0 / 256.0
        bits = struct.unpack("<I", struct.pack("<f", 1.0 + half_ulp))[0]
        halfway_up = struct.unpack("<f", struct.pack("<I", bits + 0x8000))[0]
        self.assertEqual(bf16(halfway_up), 1.0 + 1.0 / 128.0)

    def test_seven_mantissa_bits(self):
        one = struct.unpack("<I", struct.pack("<f", 1.0))[0]
        self.assertEqual(bf16(1.0 + 1.0 / 128.0), 1.0 + 1.0 / 128.0)
        self.assertEqual(bf16(1.0 + 1.0 / 256.0), 1.0)
        self.assertEqual(one & 0xFFFF, 0)

    def test_overflow_to_infinity(self):
        self.assertEqual(bf16(1e300), INF)
        self.assertEqual(bf16(-1e300), -INF)

    def test_nan_and_infinity_pass_through(self):
        nan = float("nan")
        self.assertNotEqual(bf16(nan), bf16(nan))
        self.assertEqual(bf16(INF), INF)
        self.assertEqual(bf16(-INF), -INF)


class TestShapes(unittest.TestCase):
    def test_full_model_is_about_one_million_parameters(self):
        _, m = build(len(VOCAB), "full")
        n = m.num_params()
        self.assertTrue(900000 < n < 1100000, "got %d" % n)

    def test_state_is_d_model_squared_per_layer(self):
        cfg, m = build(len(VOCAB), "tiny")
        self.assertEqual(cfg.state_size(), cfg.n_layer * cfg.d_model * cfg.d_model)

    def test_state_does_not_grow_with_context(self):
        cfg, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)
        _, s_short = m.run(ids[:8], keep_cache=False, states=m.fresh_states())
        _, s_long = m.run(ids, keep_cache=False, states=m.fresh_states())
        for a, b in zip(s_short, s_long):
            self.assertEqual(len(a), cfg.d_model)
            self.assertEqual(len(a[0]), cfg.d_model)
            self.assertEqual(len(b), len(a))
        self.assertIsNone(m.cache)

    def test_logit_shape(self):
        _, m = build(len(VOCAB), "micro")
        z = m.logits(VOCAB.encode("hello"), keep_cache=False)
        self.assertEqual(len(z), 5)
        self.assertEqual(len(z[0]), len(VOCAB))

    def test_generation_state_size_is_flat(self):
        cfg, m = build(len(VOCAB), "micro")
        state = m.fresh_states()
        sizes = []
        for _ in range(16):
            _, state = m.step_token(3, state)
            sizes.append(sum([len(r) for layer in state for r in layer]))
        self.assertEqual(len(set(sizes)), 1)
        self.assertEqual(sizes[0], cfg.n_layer * cfg.d_model * cfg.d_model)


class TestAttentionMath(unittest.TestCase):
    def test_recurrent_matches_the_non_recurrent_form(self):
        cfg, m = build(len(VOCAB), "micro")
        attn = m.blocks[0].attn
        d = cfg.d_model
        rng = Rng(11)
        steps = 9
        ns = [rng.random() - 0.5 for _ in range(steps * d)]
        s, cache = attn.forward(ns, steps, attn.zero_state)
        direct = linear_attention_parallel([c[1] for c in cache],
                                           [c[2] for c in cache],
                                           [c[3] for c in cache],
                                           [c[4] for c in cache])
        for t in range(steps):
            for i in range(d):
                self.assertAlmostEqual(cache[t][6][i], direct[t][i], places=5)

    def test_state_after_one_token_is_the_outer_product(self):
        cfg, m = build(len(VOCAB), "micro")
        attn = m.blocks[0].attn
        d = cfg.d_model
        rng = Rng(13)
        n = [rng.random() - 0.5 for _ in range(d)]
        s, cache = attn.forward(n, 1, attn.zero_state)
        k = cache[0][2]
        v = cache[0][3]
        for j in range(d):
            for i in range(d):
                self.assertAlmostEqual(s[j][i], k[j] * v[i], places=12)

    def test_gate_is_strictly_between_zero_and_one(self):
        _, m = build(len(VOCAB), "micro")
        attn = m.blocks[0].attn
        for c in attn.forward([0.1] * m.cfg.d_model, 1, attn.zero_state)[1]:
            self.assertTrue(0.0 < c[4] < 1.0)

    def test_long_context_decays_instead_of_growing(self):
        cfg, m = build(len(VOCAB), "micro")
        attn = m.blocks[0].attn
        d = cfg.d_model
        s = attn.zero_state
        n = [0.5] * d
        for _ in range(2000):
            s, cache = attn.forward(n, 1, s)
        big = 0
        for row in s:
            for v in row:
                if abs(v) > big:
                    big = abs(v)
        self.assertTrue(big < 1e5, "state grew unbounded: %g" % big)


class TestCausality(unittest.TestCase):
    def test_future_tokens_do_not_change_the_past(self):
        _, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)[:12]
        a = m.logits(ids, keep_cache=False, states=m.fresh_states())
        other = list(ids)
        other[8:] = [1, 2, 3, 4]
        b = m.logits(other, keep_cache=False, states=m.fresh_states())
        for t in range(8):
            for v in range(len(VOCAB)):
                self.assertAlmostEqual(a[t][v], b[t][v], places=10)

    def test_chunked_inference_equals_one_shot(self):
        _, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)[:10]
        whole = m.logits(ids, keep_cache=False, states=m.fresh_states())
        state = m.fresh_states()
        pieces = []
        for i in range(0, len(ids), 3):
            piece, state = m.run(ids[i:i + 3], keep_cache=False, states=state)
            w = m.emb
            block = [None] * len(piece)
            for ti, h in enumerate(piece):
                row = [0.0] * len(VOCAB)
                for v in range(len(VOCAB)):
                    row[v] = dot_(w.row(v), h)
                block[ti] = row
            pieces.append(block)
        flat = [row for piece in pieces for row in piece]
        for t in range(len(ids)):
            for v in range(len(VOCAB)):
                self.assertAlmostEqual(whole[t][v], flat[t][v], places=10)


def snapshot_grads():
    return dict((id(p), list(p.grad)) for p in Tensor.registry)


def numeric_grad(m, ids, targets, p, i, eps):
    old = p.data[i]
    p.data[i] = old + eps
    lp = m.loss_and_grads(ids, targets)[0]
    p.data[i] = old - eps
    lm = m.loss_and_grads(ids, targets)[0]
    p.data[i] = old
    return (lp - lm) / (2 * eps)


class TestGradients(unittest.TestCase):
    def _loss(self, m, ids, targets):
        return m.loss_and_grads(ids, targets)[0]

    def test_gradcheck_every_parameter(self):
        cfg, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)[:5]
        targets = ids[1:] + [ids[1]]
        self._loss(m, ids, targets)
        ref = snapshot_grads()
        eps = 1e-4
        checked = 0
        for p in list(Tensor.registry):
            for i in range(p.n):
                g = ref[id(p)][i]
                if i % 3 != 0 and abs(g) < 1e-5:
                    continue
                num = numeric_grad(m, ids, targets, p, i, eps)
                tol = 3e-3 + 0.02 * abs(num)
                self.assertLessEqual(abs(num - g), tol,
                                     "%s[%d]: analytic %.6f numeric %.6f"
                                     % (p.name, i, g, num))
                checked += 1
        self.assertTrue(checked > 50, "only checked %d entries" % checked)

    def test_gradients_are_finite(self):
        _, m = build(len(VOCAB), "tiny")
        ids = VOCAB.encode(CORPUS)[:16]
        m.loss_and_grads(ids, ids[1:] + [ids[1]])
        for p in Tensor.registry:
            for g in p.grad:
                self.assertEqual(g, g)
                self.assertLess(abs(g), 1e6)

    def test_tied_embedding_gets_gradient_from_both_directions(self):
        _, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode("abcde")
        m.loss_and_grads(ids, ids[1:] + [ids[0]])
        used = set(ids)
        touched_input = any([any(m.emb.grad_row(t)) for t in used])
        touched_head = any(
            [any(m.emb.grad_row(v)) for v in range(len(VOCAB)) if v not in used])
        self.assertTrue(touched_input, "no gradient from the input side")
        self.assertTrue(touched_head, "no gradient from the output head")

    def test_gradcheck_tiny_config(self):
        cfg, m = build(len(VOCAB), "tiny")
        ids = VOCAB.encode(CORPUS)[:4]
        targets = ids[1:] + [ids[1]]
        self._loss(m, ids, targets)
        ref = snapshot_grads()
        for p in list(Tensor.registry):
            for i in range(0, p.n, 17):
                g = ref[id(p)][i]
                if abs(g) < 1e-5:
                    continue
                num = numeric_grad(m, ids, targets, p, i, 1e-4)
                self.assertLessEqual(abs(num - g), 5e-3 + 0.02 * abs(num),
                                     "%s[%d]: %.6f vs %.6f" % (p.name, i, g, num))

    def test_input_gradient_of_the_attention(self):
        # The gradient wrt the layer input is what feeds the residual stream,
        # and it is the one path the parameter checks cannot see.
        reset_registry()
        d = 5
        steps = 4
        rng = Rng(1)
        attn = GatedLinearAttention("t", d, rng)
        ns = [rng.random() - 0.5 for _ in range(steps * d)]
        _, cache = attn.forward(ns, steps, attn.zero_state)
        gos = [[rng.random() for _ in range(d)] for _ in range(steps)]
        gns = attn.backward(cache, gos)

        def loss(inp):
            _, c = attn.forward(inp, steps, attn.zero_state)
            total = 0.0
            for t in range(steps):
                total = total + dot_(gos[t], c[t][6])
            return total

        eps = 1e-6
        for t in range(steps):
            for i in range(d):
                plus = ns[:]
                minus = ns[:]
                plus[t * d + i] = plus[t * d + i] + eps
                minus[t * d + i] = minus[t * d + i] - eps
                num = (loss(plus) - loss(minus)) / (2 * eps)
                self.assertAlmostEqual(gns[t][i], num, places=7,
                                       msg="grad wrt input [%d][%d]" % (t, i))


def mean_loss(m, pairs):
    total = 0.0
    for inp, tgt in pairs:
        total += m.loss_and_grads(inp, tgt)[0]
    return total / len(pairs)


class TestTraining(unittest.TestCase):
    def test_training_reduces_the_loss_on_a_fixed_eval_set(self):
        cfg, m = build(len(VOCAB), "tiny")
        ids = VOCAB.encode(CORPUS * 3)
        data = windows(ids, 24, 64)
        held_out = windows(ids[700:], 24, 8)
        before = mean_loss(m, held_out)
        train(m, data, 200, lr=1e-2, log_every=10 ** 9)
        after = mean_loss(m, held_out)
        self.assertLess(after, before * 0.75, "%f -> %f" % (before, after))

    def test_weights_are_bf16_after_a_step(self):
        _, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)[:8]
        m.loss_and_grads(ids, ids[1:] + [ids[1]])
        AdamW(lr=1e-2).step()
        for p in Tensor.registry:
            self.assertTrue(p.all_bf16(), p.name)

    def test_updates_below_bf16_resolution_are_erased(self):
        _, m = build(len(VOCAB), "micro")
        p = m.blocks[0].attn.o.w
        p.quantize()
        before = list(p.data)
        p.grad = [1e-9] * p.n
        AdamW(lr=1e-6, clip=0.0, wd=0.0).step()
        self.assertEqual(p.data, before)

    def test_grad_clipping_keeps_the_step_finite(self):
        _, m = build(len(VOCAB), "micro")
        ids = VOCAB.encode(CORPUS)[:8]
        m.loss_and_grads(ids, ids[1:] + [ids[1]])
        for p in Tensor.registry:
            p.grad = [g * 1e3 for g in p.grad]
        gn = AdamW(clip=1.0).grad_norm()
        self.assertGreater(gn, 1.0)
        AdamW(lr=1e-2, clip=1.0).step()
        for p in Tensor.registry:
            for d in p.data:
                self.assertEqual(d, d)
                self.assertLess(abs(d), 10.0)


class TestText(unittest.TestCase):
    def test_vocab_roundtrip(self):
        text = "the state, and the gate.\n"
        self.assertEqual(VOCAB.decode(VOCAB.encode(text)), text)

    def test_generate_returns_the_requested_length(self):
        _, m = build(len(VOCAB), "micro")
        out = generate(m, VOCAB.encode("the "), 12, 1.0, seed=4)
        self.assertEqual(len(out), 12)
        for t in out:
            self.assertTrue(0 <= t < len(VOCAB))

    def test_greedy_generation_is_deterministic(self):
        _, m = build(len(VOCAB), "micro")
        a = generate(m, VOCAB.encode("the "), 8, 0.0, seed=1)
        b = generate(m, VOCAB.encode("the "), 8, 0.0, seed=1)
        self.assertEqual(a, b)

    def test_training_teaches_the_model_something(self):
        cfg, m = build(len(VOCAB), "tiny")
        ids = VOCAB.encode(CORPUS * 3)
        data = windows(ids, 32, 32)
        held_out = windows(ids[900:], 32, 8)
        before = mean_loss(m, held_out)
        train(m, data, 300, lr=1e-2, log_every=10 ** 9)
        after = mean_loss(m, held_out)
        self.assertLess(after, before * 0.75, "%.3f -> %.3f" % (before, after))
        text = sample_text(m, VOCAB, "the ", 40, 0.7, seed=2)
        self.assertEqual(len(text), 44)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def parse_args(argv):
    steps = 40
    seq_len = 24
    kind = "full"
    new = 160
    bench = False
    for i, a in enumerate(argv):
        if a == "--bench":
            bench = True
        elif a == "--steps" and i + 1 < len(argv):
            steps = int(argv[i + 1])
        elif a == "--seq" and i + 1 < len(argv):
            seq_len = int(argv[i + 1])
        elif a == "--new" and i + 1 < len(argv):
            new = int(argv[i + 1])
        elif a == "--tiny":
            kind = "tiny"
        elif a == "--micro":
            kind = "micro"
    if bench:
        steps = 2
        seq_len = 8
        new = 8
    return steps, seq_len, kind, new, bench


def bench(model, data, seq_len, out):
    """One step of everything, timed -- the run to compare against the JIT."""
    opt = AdamW(lr=1e-3)
    inp, tgt = data[0]
    t0 = time.time()
    loss, ntok = model.loss_and_grads(inp, tgt)
    t1 = time.time()
    opt.step()
    opt.zero_grad()
    t2 = time.time()
    sys.stdout.write("loss %.4f\n" % loss)
    sys.stdout.write("fwd+bwd %d tokens  %.3f s\n" % (ntok, t1 - t0))
    sys.stdout.write("adam over %d params  %.3f s\n" % (model.num_params(), t2 - t1))
    return t2 - t0


def main(argv):
    steps, seq_len, kind, new, is_bench = parse_args(argv)
    ids = VOCAB.encode(CORPUS)
    if kind == "micro":
        cfg = Config.micro(len(VOCAB))
    elif kind == "tiny":
        cfg = Config.tiny(len(VOCAB))
    else:
        cfg = Config.full(len(VOCAB))
    model = Model(cfg)
    sys.stdout.write("config      d_model=%d n_layer=%d d_ff=%d vocab=%d\n"
              % (cfg.d_model, cfg.n_layer, cfg.d_ff, cfg.vocab))
    sys.stdout.write("parameters  %d\n" % model.num_params())
    sys.stdout.write("state       %d floats (%d per layer), %d bytes as bf16\n"
              % (cfg.state_size(), cfg.d_model * cfg.d_model, cfg.state_size() * 2))
    sys.stdout.write("corpus      %d characters\n" % len(ids))
    sys.stdout.write("training    %d steps at seq_len=%d\n\n" % (steps, seq_len))
    data = windows(ids, seq_len, 256)
    if is_bench:
        t0 = time.time()
        bench(model, data, seq_len, out)
        t1 = time.time()
        text = sample_text(model, VOCAB, "the ", new, 0.8, 3)
        sys.stdout.write("generate %d tokens  %.3f s\n" % (new, time.time() - t1))
        sys.stdout.write("total %.3f s\n" % (time.time() - t0))
        sys.stdout.write("sample: %s\n" % text.replace(chr(10), " "))
        return 0
    for line in train(model, data, steps, log_every=max(1, steps // 6),
                      prompt_ids=VOCAB.encode("the ")):
        sys.stdout.write(line + "\n")
    sys.stdout.write("\ngreedy:\n%s\n\n" % sample_text(model, VOCAB, "the model", new, 0.0))
    sys.stdout.write("sampled:\n%s\n" % sample_text(model, VOCAB, "every layer", new, 0.85, 7))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
