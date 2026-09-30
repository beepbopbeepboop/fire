#!/usr/bin/env python3
"""Markdown -> HTML, for this repo's documentation.

There is no `markdown` module available and no third-party dependency is
wanted for a build step, so this renders exactly the subset the docs here
use: ATX headings, paragraphs, fenced code, GFM pipe tables, ordered and
unordered lists (with lazy continuation), and the inline `code` / `**bold**` /
`*italic*` forms. Anything outside that subset is left as literal text rather
than guessed at, so an unsupported construct shows up as visible source
instead of silently vanishing.

Why a generator rather than a hand-written sibling file: `doc/` already has
both patterns, and the hand-maintained pair is the one that goes stale. Two
copies of the same prose cannot both be right after the next edit to the
`.md`, and nothing in the tree fails when that happens. Regenerating is
`python3 tools/md2html.py doc/GPU_OFFLOAD_PLAN.md`; the emitted file carries a
"generated from" banner naming the source and the tool, so a reader knows
which file is authoritative and an editor knows not to hand-edit the output.

    python3 tools/md2html.py doc/GPU_OFFLOAD_PLAN.md           # -> .html beside it
    python3 tools/md2html.py a.md b.md --stdout                # to stdout, for piping
    python3 tools/md2html.py --check doc/*.md                  # exit 1 if any is stale

`--check` is the one that matters in a gate: it is the difference between
"the HTML is regenerated when the Markdown changes" and "somebody remembers
to".
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys

# The house style, shared with doc/architecture.html so the docs read as one
# set. Kept here rather than in a .css file: these pages are opened straight
# off disk, and a relative <link> is one more thing that breaks when a doc is
# moved or mailed around.
CSS = """\
  body { max-width: 56em; margin: 0 auto; padding: 2em;
         font-family: system-ui, sans-serif; line-height: 1.6; color: #1a1a1a; }
  h1 { border-bottom: 2px solid #222; padding-bottom: .3em; }
  h2 { margin-top: 2.5em; border-bottom: 1px solid #ccc; padding-bottom: .2em; }
  h3 { margin-top: 1.8em; }
  h1, h2, h3, h4 { line-height: 1.25; }
  code, pre { font-family: "SF Mono", "Fira Code", monospace; font-size: 92%; }
  code { background: #f0f0f0; padding: .1em .3em; border-radius: 3px; }
  pre { background: #f5f5f5; padding: .8em 1em; border-radius: 4px;
        overflow-x: auto; line-height: 1.45; }
  pre code { background: none; padding: 0; font-size: 100%; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: .4em .7em; text-align: left;
           vertical-align: top; }
  th { background: #eee; }
  li { margin: .3em 0; }
  li > p { margin: .3em 0; }
  .banner { background: #fffbe6; border-left: 4px solid #d4a017;
            padding: .6em 1em; margin: 0 0 2em 0; font-size: 92%; color: #555; }
  .banner code { background: #f5edd0; }
  em { color: #444; }
"""

_BANNER = ('<p class="banner">Generated from <code>{src}</code> by '
           '<code>tools/md2html.py</code>. Edit the Markdown, not this file; '
           'rerun <code>python3 tools/md2html.py {src}</code>.</p>')


# ── inline ──────────────────────────────────────────────────────────────────

# Order matters. Code spans are extracted first and stashed, so a `*` or `**`
# inside `x * y * z` cannot be mistaken for emphasis, and so that escaping
# cannot mangle a code span's contents.
_CODE_RE = re.compile(r'`([^`]+)`')
_PLACEHOLDER = '\x00CODE{}\x00'


def _inline(text: str) -> str:
    """Escape, then apply code / bold / italic, with code spans protected."""
    spans: list[str] = []

    def _stash(m: re.Match) -> str:
        spans.append(f'<code>{html.escape(m.group(1), quote=False)}</code>')
        return _PLACEHOLDER.format(len(spans) - 1)

    text = _CODE_RE.sub(_stash, text)
    out = html.escape(text, quote=False)
    # `**bold**` before `*italic*`, so a bold run is not consumed as two
    # italic spans. The lookarounds keep `**` from matching inside a word.
    out = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'<strong>\1</strong>', out)
    out = re.sub(r'(?<![\*\w])\*(?=\S)(.+?)(?<=\S)\*(?!\*)', r'<em>\1</em>', out)
    for i, s in enumerate(spans):
        out = out.replace(_PLACEHOLDER.format(i), s)
    return out


# ── block parsing ───────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r'^```\s*(\S*)\s*$')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
_UL_RE = re.compile(r'^(\s*)[-*]\s+(.*)$')
_OL_RE = re.compile(r'^(\s*)(\d+)\.\s+(.*)$')
_TABLE_SEP_RE = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')


def _is_table_row(line: str) -> bool:
    return line.strip().startswith('|') and line.count('|') >= 2


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [c.strip() for c in s.split('|')]


def _render_table(rows: list[str]) -> str:
    head = _split_row(rows[0])
    body = [_split_row(r) for r in rows[2:]]
    out = ['<table>', '<thead><tr>']
    out += [f'<th>{_inline(c)}</th>' for c in head]
    out.append('</tr></thead>')
    out.append('<tbody>')
    for r in body:
        # A short row is padded rather than left ragged: the column count is
        # the header's, and a missing cell is an empty <td>, not a shifted
        # row.
        r = r + [''] * (len(head) - len(r)) if len(r) < len(head) else r[:len(head)]
        out.append('<tr>')
        out += [f'<td>{_inline(c)}</td>' for c in r]
        out.append('</tr>')
    out.append('</tbody></table>')
    return '\n'.join(out)


class _ListState:
    """Open list nesting, so a `</ul>` lands at the right indent."""

    def __init__(self) -> None:
        self.stack: list[tuple[int, str]] = []   # (indent, 'ul'|'ol')

    def open_to(self, indent: int, kind: str, out: list[str]) -> None:
        while self.stack and self.stack[-1][0] > indent:
            out.append(f'</{self.stack.pop()[1]}>')
        if not self.stack or self.stack[-1][1] != kind or self.stack[-1][0] < indent:
            if self.stack and self.stack[-1][0] == indent:
                out.append(f'</{self.stack.pop()[1]}>')
            out.append(f'<{kind}>')
            self.stack.append((indent, kind))

    def close_all(self, out: list[str]) -> None:
        while self.stack:
            out.append(f'</{self.stack.pop()[1]}>')


def _render_list(lines: list[str], start: int) -> tuple[str, int]:
    st = _ListState()
    out: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        m = _UL_RE.match(line)
        kind = 'ul'
        if m:
            indent, item = len(m.group(1)), m.group(2)
        else:
            m = _OL_RE.match(line)
            if not m:
                break
            indent, item = len(m.group(1)), m.group(3)
            kind = 'ol'
        st.open_to(indent, kind, out)
        i += 1
        # Lazy continuation: following lines indented past the marker are part
        # of this item and are joined into its paragraph. Without this a
        # wrapped item becomes two items -- which is how "Increment 2 -- the
        # hand-written speciality code." and the rest of its sentence end up
        # as separate bullets.
        #
        # The item's OWN text is kept: an earlier version REPLACED the
        # partially-built <li> with the continuation text, so every wrapped
        # item in the document rendered as its trailing clause and nothing
        # else. Cheap to write, and the whole list reads as nonsense.
        cont: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if _UL_RE.match(nxt) or _OL_RE.match(nxt):
                break
            # A continuation must be indented further than its marker. A
            # non-indented line is a new paragraph, and the caller's loop
            # handles that.
            if nxt[:1] not in (' ', '\t'):
                break
            cont.append(nxt.strip())
            i += 1
        text = _inline(item)
        if cont:
            out.append('<li><p>' + text + ' ' + _inline(' '.join(cont))
                       + '</p></li>')
        else:
            out.append('<li>' + text + '</li>')
    st.close_all(out)
    return '\n'.join(out), i


def convert(md: str, src_name: str) -> str:
    lines = md.split('\n')
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            lang = fence.group(1)
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1   # closing fence
            cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ''
            out.append(f'<pre><code{cls}>'
                       f'{html.escape(chr(10).join(body), quote=False)}</code></pre>')
            continue

        h = _HEADING_RE.match(line)
        if h:
            lvl = len(h.group(1))
            out.append(f'<h{lvl}>{_inline(h.group(2))}</h{lvl}>')
            i += 1
            continue

        # A table is a row, an alignment separator, then more rows.
        if (_is_table_row(line) and i + 1 < len(lines)
                and _TABLE_SEP_RE.match(lines[i + 1])
                and _is_table_row(lines[i + 1])):
            # The separator IS part of `rows`: _render_table's contract is
            # rows[0]=header, rows[1]=alignment separator, rows[2:]=body.
            # Leaving it out (collecting only the body after `i += 2`) made
            # rows[2:] silently drop the FIRST BODY ROW -- the "build wiring"
            # comparison in the GPU offload plan just vanished from the HTML
            # with no error anywhere. A row that is quietly not rendered looks
            # exactly like a row that was never written.
            rows = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue

        if _UL_RE.match(line) or _OL_RE.match(line):
            html_block, i = _render_list(lines, i)
            out.append(html_block)
            continue

        para: list[str] = []
        while i < len(lines) and lines[i].strip():
            nxt = lines[i]
            if (_HEADING_RE.match(nxt) or _FENCE_RE.match(nxt)
                    or _UL_RE.match(nxt) or _OL_RE.match(nxt)
                    or (_is_table_row(nxt) and i + 1 < len(lines)
                        and _TABLE_SEP_RE.match(lines[i + 1]))):
                break
            para.append(nxt.strip())
            i += 1
        if para:
            out.append(f'<p>{_inline(" ".join(para))}</p>')
        else:
            i += 1

    title = 'Documentation'
    m = _HEADING_RE.match(lines[0]) if lines else None
    if m:
        title = m.group(2)
        title = re.sub(r'`|\*\*|\*', '', title)

    return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{html.escape(title)}</title>\n<style>\n{CSS}</style>\n</head>\n'
            f'<body>\n\n{_BANNER.format(src=html.escape(src_name, quote=True))}\n\n'
            + '\n'.join(out)
            + '\n\n</body>\n</html>\n')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--stdout', action='store_true',
                    help='write to stdout instead of a sibling .html')
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if any .html is missing or stale')
    args = ap.parse_args(argv)

    stale: list[str] = []
    for path in args.files:
        with open(path, encoding='utf-8') as f:
            md = f.read()
        out = convert(md, os.path.basename(path))
        dest = os.path.splitext(path)[0] + '.html'
        if args.stdout:
            sys.stdout.write(out)
            continue
        if args.check:
            try:
                with open(dest, encoding='utf-8') as f:
                    cur = f.read()
            except OSError:
                cur = None
            if cur != out:
                stale.append(f'{path} -> {dest}')
            continue
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(out)
        print(f'{path} -> {dest}')

    if stale:
        print('stale generated HTML:\n  ' + '\n  '.join(stale),
              file=sys.stderr)
        print('regenerate with: python3 tools/md2html.py ' + ' '.join(stale),
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
