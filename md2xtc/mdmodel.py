# -*- coding: utf-8 -*-
"""
Markdown -> block model.

The block model is what the typesetter draws. It is deliberately flat:
lists are already numbered, quote depth is a number on the block, and
inline styling is a list of fragments.

Parsing is done by markdown-it-py (CommonMark + GFM tables and
strikethrough). Front matter, footnotes and task list boxes are handled
here, because they are not part of the base parser.
"""

import os
import re

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover - reported by the caller
    MarkdownIt = None


# ----------------------------------------------------------------------
# Pieces
# ----------------------------------------------------------------------

class Frag(object):
    """A run of text with one look."""

    __slots__ = ("text", "bold", "italic", "mono", "strike", "link", "br")

    def __init__(self, text, bold=False, italic=False, mono=False,
                 strike=False, link=None, br=False):
        self.text = text
        self.bold = bold
        self.italic = italic
        self.mono = mono
        self.strike = strike
        self.link = link
        self.br = br

    def copy(self, text):
        return Frag(text, self.bold, self.italic, self.mono,
                    self.strike, self.link, self.br)

    def __repr__(self):
        return "Frag(%r%s%s%s)" % (self.text,
                                   " b" if self.bold else "",
                                   " i" if self.italic else "",
                                   " m" if self.mono else "")


class Block(object):
    """One thing to draw: paragraph, heading, list item, code, table...

    kind is one of:
      para heading item code rule table image pagebreak
    """

    def __init__(self, kind, **kw):
        self.kind = kind
        self.frags = kw.get("frags") or []
        self.level = kw.get("level", 0)      # heading level
        self.indent = kw.get("indent", 0)    # list depth, 0 = none
        self.quote = kw.get("quote", 0)      # blockquote depth
        self.marker = kw.get("marker", "")   # bullet or number text
        self.lines = kw.get("lines") or []   # code lines
        self.lang = kw.get("lang", "")
        self.head = kw.get("head")           # table header cells
        self.rows = kw.get("rows") or []     # table body rows
        self.align = kw.get("align") or []   # table column alignment
        self.src = kw.get("src", "")         # image path
        self.alt = kw.get("alt", "")
        self.tight = kw.get("tight", False)  # tight list item
        self.anchor = kw.get("anchor")       # heading text for the contents

    def text(self):
        return "".join(f.text for f in self.frags)

    def __repr__(self):
        return "<%s %r>" % (self.kind, self.text()[:40])


class Document(object):
    def __init__(self):
        self.title = ""
        self.author = ""
        self.blocks = []
        self.base_dir = "."
        self.meta_title = False        # title came from the front matter


# ----------------------------------------------------------------------
# Front matter
# ----------------------------------------------------------------------

FM_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)


def split_front_matter(text):
    """Pull a YAML-ish front matter block off the top. No yaml needed."""
    meta = {}
    m = FM_RE.match(text)
    if not m:
        return meta, text
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip().strip('"').strip("'")
        if v.startswith("[") and v.endswith("]"):
            v = v[1:-1].replace('"', "").replace("'", "")
        meta[k.strip().lower()] = v
    return meta, text[m.end():]


# ----------------------------------------------------------------------
# Footnotes
# ----------------------------------------------------------------------

FN_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*)$")


def split_footnotes(text):
    """Take [^id]: ... definitions out of the text.

    Returns (text without definitions, ordered list of (id, body)).
    """
    out_lines = []
    notes = []
    cur = None
    for line in text.splitlines():
        m = FN_DEF_RE.match(line)
        if m:
            cur = [m.group(1), m.group(2).strip()]
            notes.append(cur)
            continue
        if cur is not None:
            if not line.strip():
                cur = None
                out_lines.append(line)
                continue
            if line[:1] in (" ", "\t"):
                cur[1] += " " + line.strip()
                continue
            cur = None
        out_lines.append(line)
    return "\n".join(out_lines), notes


# ----------------------------------------------------------------------
# Inline walk
# ----------------------------------------------------------------------

CJK_SOFTBREAK = re.compile(
    r"[ᄀ-ᇿ⺀-鿿ꥠ-꥿가-퟿豈-﫿"
    r"︰-﹏＀-｠￠-￦]")

BULLETS = ("•", "◦", "▪", "‣")

# Chinese and Japanese wrap without spaces, so a line break in the source
# is not a space. Korean writes spaces between words, so there it is.
HAN_KANA = re.compile(r"[\u2e80-\u30ff\u3190-\u4dbf\u4e00-\u9fff"
                      r"\uf900-\ufaff]")


def _is_cjk(ch):
    return bool(ch) and bool(CJK_SOFTBREAK.match(ch))


def _is_han_kana(ch):
    return bool(ch) and bool(HAN_KANA.match(ch))


class _Inline(object):
    """Walks the children of one inline token into a fragment list."""

    def __init__(self, opts, fn_index):
        self.opts = opts
        self.fn_index = fn_index      # footnote id -> number
        self.images = []              # images met inside the run

    def run(self, token):
        frags = []
        bold = ital = strike = 0
        link = [None]
        if token is None or not token.children:
            if token is not None and token.content:
                frags.append(Frag(token.content))
            return frags

        def push(text, mono=False):
            if not text:
                return
            frags.append(Frag(text, bold > 0, ital > 0, mono,
                              strike > 0, link[0]))

        kids = token.children
        for ci, t in enumerate(kids):
            ty = t.type
            if ty == "text":
                push(self._footnote_marks(t.content))
            elif ty == "code_inline":
                push(t.content, mono=True)
            elif ty == "strong_open":
                bold += 1
            elif ty == "strong_close":
                bold = max(0, bold - 1)
            elif ty in ("em_open",):
                ital += 1
            elif ty in ("em_close",):
                ital = max(0, ital - 1)
            elif ty == "s_open":
                strike += 1
            elif ty == "s_close":
                strike = max(0, strike - 1)
            elif ty == "link_open":
                link[0] = t.attrGet("href") or ""
            elif ty == "link_close":
                if self.opts.get("show_urls") and link[0] and \
                        not link[0].startswith("#"):
                    old = link[0]
                    link[0] = None
                    push(" (%s)" % old)
                link[0] = None
            elif ty == "softbreak" and self.opts.get("breaks"):
                # every new line in a paragraph is a line break (the site's reader does this)
                frags.append(Frag("", br=True))
            elif ty == "softbreak":
                prev = frags[-1].text[-1:] if frags and frags[-1].text else ""
                nxt = ""
                for t2 in kids[ci + 1:]:
                    if t2.content:
                        nxt = t2.content[:1]
                        break
                drop = _is_han_kana(prev) and _is_han_kana(nxt)
                push("" if drop else " ")
            elif ty == "hardbreak":
                frags.append(Frag("", br=True))
            elif ty == "image":
                alt = t.content or ""
                src = t.attrGet("src") or ""
                self.images.append((src, alt))
                push("[%s]" % alt if alt else "[그림]")
            elif ty == "html_inline":
                low = t.content.lower()
                if low.startswith("<br"):
                    frags.append(Frag("", br=True))
                elif low.startswith("<b>") or low.startswith("<strong>"):
                    bold += 1
                elif low.startswith("</b>") or low.startswith("</strong>"):
                    bold = max(0, bold - 1)
                elif low.startswith("<i>") or low.startswith("<em>"):
                    ital += 1
                elif low.startswith("</i>") or low.startswith("</em>"):
                    ital = max(0, ital - 1)
            elif ty in ("text_special", "emoji"):
                push(t.content)
        return [f for f in frags if f.text or f.br]

    def _footnote_marks(self, text):
        if not self.fn_index or "[^" not in text:
            return text

        def sub(m):
            n = self.fn_index.get(m.group(1))
            return ("[%d]" % n) if n else m.group(0)

        return re.sub(r"\[\^([^\]\s]+)\]", sub, text)


# ----------------------------------------------------------------------
# Token walk
# ----------------------------------------------------------------------

IMG_TAG_RE = re.compile(r"""<img[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.I)
TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TASK_RE = re.compile(r"^\[([ xX])\]\s+")
PAGEBREAK_RE = re.compile(r"<!--\s*(?:pagebreak|newpage|쪽나눔)\s*-->", re.I)


def _order_marker(n, depth):
    return "%d." % n


def parse(text, base_dir=".", opts=None):
    """Markdown text -> Document."""
    if MarkdownIt is None:
        raise RuntimeError("markdown-it-py가 없습니다")
    opts = opts or {}

    doc = Document()
    doc.base_dir = base_dir

    meta, text = split_front_matter(text)
    doc.title = meta.get("title", "")
    doc.meta_title = bool(doc.title)
    doc.author = meta.get("author", "") or meta.get("authors", "")

    text, notes = split_footnotes(text)
    fn_index = {}
    for i, (nid, _body) in enumerate(notes):
        fn_index[nid] = i + 1

    text = PAGEBREAK_RE.sub("\n\n<!--MD2XTC-PAGEBREAK-->\n\n", text)

    md = MarkdownIt("gfm-like", {"html": True, "linkify": False,
                                 "typographer": False})
    tokens = md.parse(text)

    blocks = []
    inline = _Inline(opts, fn_index)

    quote = 0
    list_stack = []      # [{'ordered':bool,'n':int}]
    pending_marker = [None]
    tight_stack = []

    def add(block):
        block.quote = quote
        block.indent = len(list_stack)
        blocks.append(block)

    i = 0
    while i < len(tokens):
        t = tokens[i]
        ty = t.type

        if ty == "heading_open":
            level = int(t.tag[1])
            frags = inline.run(tokens[i + 1] if i + 1 < len(tokens) else None)
            b = Block("heading", frags=frags, level=level)
            b.anchor = "".join(f.text for f in frags).strip()
            add(b)
            i += 3
            continue

        if ty == "paragraph_open":
            tok = tokens[i + 1] if i + 1 < len(tokens) else None
            before = len(inline.images)
            frags = inline.run(tok)
            imgs = inline.images[before:]
            plain = "".join(f.text for f in frags).strip()
            only_image = (len(imgs) == 1 and
                          plain in ("[%s]" % (imgs[0][1] or ""), "[그림]"))
            if only_image:
                add(Block("image", src=imgs[0][0], alt=imgs[0][1]))
            elif frags:
                b = Block("para", frags=frags,
                          tight=bool(tight_stack and tight_stack[-1]))
                if pending_marker[0] is not None:
                    b.kind = "item"
                    b.marker = pending_marker[0]
                    pending_marker[0] = None
                add(b)
            i += 3
            continue

        if ty in ("fence", "code_block"):
            lines = t.content.rstrip("\n").split("\n")
            add(Block("code", lines=lines, lang=(t.info or "").strip()))
            i += 1
            continue

        if ty == "hr":
            add(Block("rule"))
            i += 1
            continue

        if ty == "blockquote_open":
            quote += 1
            i += 1
            continue
        if ty == "blockquote_close":
            quote = max(0, quote - 1)
            i += 1
            continue

        if ty in ("bullet_list_open", "ordered_list_open"):
            start = t.attrGet("start")
            list_stack.append({"ordered": ty.startswith("ordered"),
                               "n": int(start) - 1 if start else 0})
            tight_stack.append(not _loose_list(tokens, i))
            i += 1
            continue

        if ty in ("bullet_list_close", "ordered_list_close"):
            if list_stack:
                list_stack.pop()
            if tight_stack:
                tight_stack.pop()
            i += 1
            continue

        if ty == "list_item_open":
            if list_stack:
                top = list_stack[-1]
                depth = len(list_stack)
                if top["ordered"]:
                    top["n"] += 1
                    pending_marker[0] = _order_marker(top["n"], depth)
                else:
                    pending_marker[0] = BULLETS[(depth - 1) % len(BULLETS)]
            i += 1
            continue

        if ty == "list_item_close":
            pending_marker[0] = None
            i += 1
            continue

        if ty == "table_open":
            i, tb = _read_table(tokens, i, inline)
            add(tb)
            continue

        if ty in ("html_block",):
            body = t.content
            if "MD2XTC-PAGEBREAK" in body:
                add(Block("pagebreak"))
                i += 1
                continue
            m = IMG_TAG_RE.search(body)
            if m:
                add(Block("image", src=m.group(1), alt=""))
                i += 1
                continue
            body = COMMENT_RE.sub("", body)
            body = TAG_RE.sub(" ", body)
            body = re.sub(r"[ \t]+", " ", body).strip()
            if body:
                add(Block("para", frags=[Frag(body)]))
            i += 1
            continue

        i += 1

    # task list boxes: "[ ] " at the head of a bullet item
    for b in blocks:
        if b.kind == "item" and b.frags and not b.marker[:1].isdigit():
            m = TASK_RE.match(b.frags[0].text)
            if m:
                b.marker = "☑" if m.group(1) in "xX" else "☐"
                b.frags[0] = b.frags[0].copy(b.frags[0].text[m.end():])

    if notes:
        name = opts.get("notes_title") or "auto"
        if name.lower() in ("auto", "자동"):
            name = "주석" if re.search(r"[\uac00-\ud7ff]", text) else "Notes"
        blocks.append(Block("rule"))
        blocks.append(Block("heading", level=3, frags=[Frag(name)]))
        for i, (_nid, body) in enumerate(notes):
            sub = md.parse(body)
            frags = []
            for tk in sub:
                if tk.type == "inline":
                    frags.extend(inline.run(tk))
            blocks.append(Block("item", marker="[%d]" % (i + 1),
                                frags=frags or [Frag(body)], indent=1,
                                tight=True))

    doc.blocks = blocks
    if not doc.title:
        for b in blocks:
            if b.kind == "heading" and b.level == 1:
                doc.title = b.text().strip()
                break
    return doc


def _loose_list(tokens, i):
    """A list is loose when any of its items holds a blank line."""
    depth = 0
    for t in tokens[i:]:
        if t.type.endswith("_list_open"):
            depth += 1
        elif t.type.endswith("_list_close"):
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and t.type == "paragraph_open" and not t.hidden:
            return True
    return False


def _read_table(tokens, i, inline):
    head = None
    rows = []
    align = []
    row = None
    in_head = False
    while i < len(tokens):
        t = tokens[i]
        ty = t.type
        if ty == "table_close":
            i += 1
            break
        if ty == "thead_open":
            in_head = True
        elif ty == "thead_close":
            in_head = False
        elif ty == "tr_open":
            row = []
        elif ty == "tr_close":
            if in_head:
                head = row
            elif row is not None:
                rows.append(row)
            row = None
        elif ty in ("th_open", "td_open"):
            style = (t.attrGet("style") or "")
            a = "left"
            if "center" in style:
                a = "center"
            elif "right" in style:
                a = "right"
            cell = inline.run(tokens[i + 1]) if i + 1 < len(tokens) and \
                tokens[i + 1].type == "inline" else []
            if row is not None:
                row.append(cell)
                if in_head:
                    align.append(a)
                elif len(align) < len(row):
                    align.append(a)
        i += 1
    return i, Block("table", head=head, rows=rows, align=align)


def read_markdown(path, opts=None):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    doc = parse(text, os.path.dirname(os.path.abspath(path)), opts)
    if not doc.title:
        doc.title = os.path.splitext(os.path.basename(path))[0]
    return doc
