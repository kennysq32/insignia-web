# -*- coding: utf-8 -*-
"""
Typesetter: block model -> pages of pixels.

Markdown reflows, so unlike a PDF nothing is scaled down here. Text is
laid out at the size of the reader screen, which is why it stays sharp.

The work goes in three steps:

  blocks -> lines     one line of a paragraph, one row of a table, ...
  lines  -> pages     greedy fill, with keep-together and orphan rules
  page   -> pixels    drawing ops are played onto a grey sheet

A line carries drawing ops with y measured from the top of the line, so
the paginator can move a line anywhere without touching its contents.
"""

import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Characters
# ----------------------------------------------------------------------

_CJK = re.compile(
    r"[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7ff"
    r"\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]")

# Do not let these open a line.
NO_LINE_START = set("。、，．,.!?！？：；:;)）]｝}〉》」』】〕”’·…ㆍ%℃")
# Do not let these end a line.
NO_LINE_END = set("(（[｛{〈《「『【〔“‘#$￦￥£")

WS = set(" \t\u00a0\u3000")


def is_cjk(ch):
    return bool(_CJK.match(ch))


# ----------------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------------

WIN = os.environ.get("SystemRoot", "C:\\Windows") + "\\Fonts\\"
MAC = "/System/Library/Fonts/"
MACX = MAC + "Supplemental/"
LIN = "/usr/share/fonts/"

# each entry: (path, face index inside a .ttc)
CANDIDATES = {
    ("serif", "r"): [
        (LIN + "truetype/dejavu/DejaVuSerif.ttf", 0),
        (LIN + "truetype/liberation/LiberationSerif-Regular.ttf", 0),
        (LIN + "opentype/urw-base35/NimbusRoman-Regular.otf", 0),
        (WIN + "georgia.ttf", 0), (WIN + "times.ttf", 0),
        (MACX + "Georgia.ttf", 0), (MACX + "Times New Roman.ttf", 0),
    ],
    ("serif", "b"): [
        (LIN + "truetype/dejavu/DejaVuSerif-Bold.ttf", 0),
        (LIN + "truetype/liberation/LiberationSerif-Bold.ttf", 0),
        (LIN + "opentype/urw-base35/NimbusRoman-Bold.otf", 0),
        (WIN + "georgiab.ttf", 0), (WIN + "timesbd.ttf", 0),
        (MACX + "Georgia Bold.ttf", 0),
    ],
    ("serif", "i"): [
        (LIN + "truetype/dejavu/DejaVuSerif-Italic.ttf", 0),
        (LIN + "truetype/liberation/LiberationSerif-Italic.ttf", 0),
        (LIN + "opentype/urw-base35/NimbusRoman-Italic.otf", 0),
        (WIN + "georgiai.ttf", 0), (WIN + "timesi.ttf", 0),
        (MACX + "Georgia Italic.ttf", 0),
    ],
    ("serif", "bi"): [
        (LIN + "truetype/dejavu/DejaVuSerif-BoldItalic.ttf", 0),
        (LIN + "truetype/liberation/LiberationSerif-BoldItalic.ttf", 0),
        (LIN + "opentype/urw-base35/NimbusRoman-BoldItalic.otf", 0),
        (WIN + "georgiaz.ttf", 0), (WIN + "timesbi.ttf", 0),
    ],
    ("sans", "r"): [
        (LIN + "truetype/dejavu/DejaVuSans.ttf", 0),
        (LIN + "truetype/liberation/LiberationSans-Regular.ttf", 0),
        (WIN + "segoeui.ttf", 0), (WIN + "arial.ttf", 0),
        (MACX + "Arial.ttf", 0), (MAC + "Helvetica.ttc", 0),
    ],
    ("sans", "b"): [
        (LIN + "truetype/dejavu/DejaVuSans-Bold.ttf", 0),
        (LIN + "truetype/liberation/LiberationSans-Bold.ttf", 0),
        (WIN + "segoeuib.ttf", 0), (WIN + "arialbd.ttf", 0),
        (MACX + "Arial Bold.ttf", 0),
    ],
    ("sans", "i"): [
        (LIN + "truetype/dejavu/DejaVuSans-Oblique.ttf", 0),
        (LIN + "truetype/liberation/LiberationSans-Italic.ttf", 0),
        (WIN + "segoeui.ttf", 0), (WIN + "ariali.ttf", 0),
    ],
    ("sans", "bi"): [
        (LIN + "truetype/dejavu/DejaVuSans-BoldOblique.ttf", 0),
        (LIN + "truetype/liberation/LiberationSans-BoldItalic.ttf", 0),
        (WIN + "arialbi.ttf", 0),
    ],
    ("mono", "r"): [
        (LIN + "truetype/dejavu/DejaVuSansMono.ttf", 0),
        (LIN + "truetype/liberation/LiberationMono-Regular.ttf", 0),
        (WIN + "consola.ttf", 0), (WIN + "cour.ttf", 0),
        (MAC + "Menlo.ttc", 0), (MACX + "Courier New.ttf", 0),
    ],
    ("mono", "b"): [
        (LIN + "truetype/dejavu/DejaVuSansMono-Bold.ttf", 0),
        (LIN + "truetype/liberation/LiberationMono-Bold.ttf", 0),
        (WIN + "consolab.ttf", 0), (WIN + "courbd.ttf", 0),
    ],
}

# Korean / CJK faces. Index 1 of the Noto collections is the KR face.
CJK_CANDIDATES = {
    ("serif", "r"): [
        (LIN + "opentype/noto/NotoSerifCJK-Regular.ttc", 1),
        (LIN + "opentype/noto/NotoSerifKR-Regular.otf", 0),
        (LIN + "truetype/noto/NotoSerifCJK-Regular.ttc", 1),
        (WIN + "batang.ttc", 0), (WIN + "malgun.ttf", 0),
        (MACX + "AppleMyungjo.ttf", 0), (MAC + "AppleSDGothicNeo.ttc", 0),
    ],
    ("serif", "b"): [
        (LIN + "opentype/noto/NotoSerifCJK-Bold.ttc", 1),
        (LIN + "opentype/noto/NotoSerifKR-Bold.otf", 0),
        (WIN + "batang.ttc", 0), (WIN + "malgunbd.ttf", 0),
    ],
    ("sans", "r"): [
        (LIN + "opentype/noto/NotoSansCJK-Regular.ttc", 1),
        (LIN + "opentype/noto/NotoSansKR-Regular.otf", 0),
        (WIN + "malgun.ttf", 0), (WIN + "gulim.ttc", 0),
        (MAC + "AppleSDGothicNeo.ttc", 0),
    ],
    ("sans", "b"): [
        (LIN + "opentype/noto/NotoSansCJK-Bold.ttc", 1),
        (LIN + "opentype/noto/NotoSansKR-Bold.otf", 0),
        (WIN + "malgunbd.ttf", 0), (WIN + "gulim.ttc", 0),
    ],
    ("mono", "r"): [
        (LIN + "opentype/noto/NotoSansCJK-Regular.ttc", 6),
        (WIN + "gulimche.ttc", 0), (WIN + "malgun.ttf", 0),
    ],
    ("mono", "b"): [
        (LIN + "opentype/noto/NotoSansCJK-Bold.ttc", 6),
        (WIN + "malgunbd.ttf", 0),
    ],
}

SYMBOL_CANDIDATES = [
    (LIN + "truetype/dejavu/DejaVuSans.ttf", 0),
    (LIN + "opentype/noto/NotoSansCJK-Regular.ttc", 1),
    (WIN + "seguisym.ttf", 0), (WIN + "arial.ttf", 0),
    (MACX + "Arial Unicode.ttf", 0),
]


def _first_existing(cands):
    for path, idx in cands:
        if os.path.isfile(path):
            return (path, idx)
    return None


def _slot(bold, italic):
    if bold and italic:
        return "bi"
    if bold:
        return "b"
    if italic:
        return "i"
    return "r"


class Face(object):
    """One size of one style, with fallback fonts behind it."""

    def __init__(self, fonts, book):
        self.fonts = [f for f in fonts if f is not None]
        self.book = book
        asc = desc = 0
        for f in self.fonts[:2]:
            a, d = f.getmetrics()
            asc = max(asc, a)
            desc = max(desc, d)
        self.ascent = asc or 1
        self.descent = desc or 1
        self._cache = {}

    def pick(self, ch):
        """Which font can draw this character. None when nobody can."""
        got = self._cache.get(ch)
        if got is not None:
            return self.fonts[got] if got >= 0 else None
        order = list(range(len(self.fonts)))
        if is_cjk(ch) and len(self.fonts) > 1:
            order = [1] + [i for i in order if i != 1]
        for i in order:
            if self.book.covers(self.fonts[i], ch):
                self._cache[ch] = i
                return self.fonts[i]
        self._cache[ch] = -1
        return None

    def segs(self, text):
        """Split into runs that one font can draw. Missing chars fall out."""
        out = []
        cur = []
        cur_font = None
        for ch in text:
            f = self.pick(ch) if (ord(ch) > 126 or not self.fonts) else \
                self.fonts[0]
            if f is None:
                self.book.dropped += 1
                continue
            if f is not cur_font:
                if cur:
                    out.append(("".join(cur), cur_font))
                cur = []
                cur_font = f
            cur.append(ch)
        if cur:
            out.append(("".join(cur), cur_font))
        return out

    def length(self, text):
        return sum(f.getlength(s) for s, f in self.segs(text))


class FontBook(object):
    """Loads faces once and remembers them."""

    def __init__(self, family="serif", overrides=None):
        self.family = family if family in ("serif", "sans") else "serif"
        self.overrides = overrides or {}
        self._files = {}
        self._faces = {}
        self._cover = {}
        self._probe = {}
        self.dropped = 0
        self.missing = []

    # -- font files ----------------------------------------------------

    def _file(self, role, slot):
        key = (role, slot)
        if key in self._files:
            return self._files[key]

        over = self.overrides.get("%s_%s" % (role, slot)) or \
            self.overrides.get(role if slot == "r" else "")
        found = None
        if over and os.path.isfile(over):
            found = (over, 0)

        fam = "mono" if role == "mono" else self.family
        if found is None:
            found = _first_existing(CANDIDATES.get((fam, slot), []))
        if found is None and slot in ("i", "bi"):          # no italic file
            found = self._file(role, "b" if slot == "bi" else "r")
        if found is None and slot == "b":
            found = self._file(role, "r")
        if found is None:
            for f2 in ("serif", "sans", "mono"):
                found = _first_existing(CANDIDATES.get((f2, "r"), []))
                if found:
                    break
        self._files[key] = found
        return found

    def _cjk_file(self, role, slot):
        key = ("cjk", role, slot)
        if key in self._files:
            return self._files[key]
        over = self.overrides.get("cjk")
        found = (over, 0) if over and os.path.isfile(over) else None
        fam = "mono" if role == "mono" else self.family
        if found is None:
            slot2 = "b" if slot in ("b", "bi") else "r"
            found = _first_existing(CJK_CANDIDATES.get((fam, slot2), []))
            if found is None:
                found = _first_existing(CJK_CANDIDATES.get(("sans", slot2), []))
        self._files[key] = found
        return found

    def _load(self, spec, size):
        if spec is None:
            return None
        path, idx = spec
        try:
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                if path not in self.missing:
                    self.missing.append(path)
                return None

    def face(self, role="body", size=16, bold=False, italic=False):
        size = max(6, int(round(size)))
        role = "mono" if role == "mono" else "body"
        slot = _slot(bold, italic)
        key = (role, size, slot)
        got = self._faces.get(key)
        if got is not None:
            return got
        fonts = [self._load(self._file(role, slot), size),
                 self._load(self._cjk_file(role, slot), size),
                 self._load(_first_existing(SYMBOL_CANDIDATES), size)]
        fonts = [f for f in fonts if f is not None]
        if not fonts:
            fonts = [ImageFont.load_default()]
        f = Face(fonts, self)
        self._faces[key] = f
        return f

    # -- glyph coverage -------------------------------------------------

    def covers(self, font, ch):
        key = (id(font), ch)
        got = self._cover.get(key)
        if got is None:
            got = self._render_probe(font, ch) != self._notdef(font)
            self._cover[key] = got
        return got

    def _notdef(self, font):
        key = id(font)
        got = self._probe.get(key)
        if got is None:
            got = self._render_probe(font, "\uffff")
            self._probe[key] = got
        return got

    @staticmethod
    def _render_probe(font, ch):
        try:
            size = getattr(font, "size", 16) or 16
            box = int(size * 2) + 8
            im = Image.new("L", (box, box), 255)
            d = ImageDraw.Draw(im)
            d.text((4, box - 6), ch, font=font, fill=0, anchor="ls")
            return im.tobytes()
        except Exception:
            return b""


# ----------------------------------------------------------------------
# Look of the page
# ----------------------------------------------------------------------

class Theme(object):
    def __init__(self, cfg):
        self.w, self.h = cfg.canvas()
        self.four = cfg.four_level

        self.size = cfg.font_size
        self.line = max(1.0, cfg.line_spacing)
        self.align = cfg.align                    # left | justify
        self.family = cfg.font_family

        m = cfg.margin
        self.ml = self.mr = m
        self.mt = cfg.margin_top if cfg.margin_top >= 0 else m
        self.mb = cfg.margin_bottom if cfg.margin_bottom >= 0 else m

        self.footer = cfg.page_numbers
        self.footer_size = max(9, int(round(self.size * 0.62)))
        self.footer_gap = self.footer_size + 6 if self.footer else 0

        self.content_w = self.w - self.ml - self.mr
        self.content_h = self.h - self.mt - self.mb - self.footer_gap

        self.h_scale = (1.75, 1.48, 1.28, 1.13, 1.03, 0.95)
        self.mono_ratio = 0.86
        self.list_indent = max(14, int(round(self.size * 1.15)))
        self.quote_indent = max(14, int(round(self.size * 1.1)))
        self.para_gap = max(4, int(round(self.size * cfg.para_spacing)))
        self.code_pad = 5
        self.ink = 0
        self.muted = 96 if self.four else 0
        self.rule_ink = 128 if self.four else 0
        self.book = None                          # set by the caller
        WORD_BREAK[0] = (getattr(cfg, "line_break", "char") == "word")
        self.chapter_break = cfg.chapter_break
        self.show_urls = cfg.show_urls
        self.image_max = cfg.image_max

    def body_h(self, size=None):
        return int(round((size or self.size) * self.line))


# ----------------------------------------------------------------------
# Inline atoms
# ----------------------------------------------------------------------

class Atom(object):
    __slots__ = ("text", "face", "ink", "under", "strike", "w", "kind")

    def __init__(self, text, face, ink, under, strike, kind):
        self.text = text
        self.face = face
        self.ink = ink
        self.under = under
        self.strike = strike
        self.kind = kind
        self.w = face.length(text) if kind != "br" else 0.0


def atomize(frags, book, theme, size, bold=False, italic=False, ink=None,
            role="body", underline_links=True):
    """Fragments -> atoms that the line breaker can move around."""
    out = []
    ink = theme.ink if ink is None else ink
    for fr in frags:
        if fr.br:
            out.append(Atom("", book.face(role, size), ink, False, False, "br"))
            continue
        if not fr.text:
            continue
        f_role = "mono" if fr.mono else role
        f_size = int(round(size * theme.mono_ratio)) if fr.mono else size
        face = book.face(f_role, f_size, bold or fr.bold, italic or fr.italic)
        under = bool(fr.link) and underline_links
        buf = []
        for ch in fr.text:
            if ch in WS:
                if buf:
                    out.append(Atom("".join(buf), face, ink, under,
                                    fr.strike, "word"))
                    buf = []
                out.append(Atom(" ", face, ink, False, False, "space"))
            elif is_cjk(ch):
                if buf:
                    out.append(Atom("".join(buf), face, ink, under,
                                    fr.strike, "word"))
                    buf = []
                out.append(Atom(ch, face, ink, under, fr.strike, "cjk"))
            else:
                buf.append(ch)
        if buf:
            out.append(Atom("".join(buf), face, ink, under, fr.strike, "word"))
    return out


# Hangul is written with spaces between words, so it can be broken either
# between syllables (an even right edge, what most Korean readers do) or
# only at spaces (a ragged edge, but no word is ever cut).
WORD_BREAK = [False]

_HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f"
                     r"\uac00-\ud7ff]")


def _can_break(prev, cur):
    if prev is None or cur.kind == "space":
        return False
    if prev.kind == "space":
        return True
    if prev.kind == "cjk" or cur.kind == "cjk":
        if cur.text[:1] in NO_LINE_START:
            return False
        if prev.text[-1:] in NO_LINE_END:
            return False
        if WORD_BREAK[0] and (_HANGUL.match(prev.text[-1:] or " ") or
                              _HANGUL.match(cur.text[:1] or " ")):
            return False
        return True
    return False


def _split_wide(atom, avail):
    """Cut a single atom that cannot fit on any line."""
    parts = []
    text = atom.text
    while text:
        lo, hi = 1, len(text)
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if atom.face.length(text[:mid]) <= avail:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        parts.append(Atom(text[:best], atom.face, atom.ink, atom.under,
                          atom.strike, atom.kind))
        text = text[best:]
        if len(parts) > 400:
            break
    return parts


def break_lines(atoms, width, first_indent=0.0, rest_indent=0.0):
    """Greedy line breaker. Returns [(atoms, width, hard_end)]."""
    lines = []
    cur = []
    w = 0.0
    last_break = -1
    indent = first_indent

    def avail():
        return width - indent

    def flush(hard=False):
        nonlocal cur, w, last_break, indent
        while cur and cur[-1].kind == "space":
            cur.pop()
        lines.append((cur, sum(a.w for a in cur), hard))
        cur = []
        w = 0.0
        last_break = -1
        indent = rest_indent

    i = 0
    while i < len(atoms):
        a = atoms[i]
        if a.kind == "br":
            flush(hard=True)
            i += 1
            continue
        if not cur and a.kind == "space":
            i += 1
            continue
        if w + a.w <= avail() + 0.01:
            if _can_break(cur[-1] if cur else None, a):
                last_break = len(cur)
            cur.append(a)
            w += a.w
            i += 1
            continue

        # does not fit
        if not cur:
            for part in _split_wide(a, avail()):
                lines.append(([part], part.w, False))
                indent = rest_indent
            i += 1
            continue
        if _can_break(cur[-1], a):
            flush()
            continue
        if last_break > 0:
            tail = cur[last_break:]
            cur = cur[:last_break]
            w = sum(x.w for x in cur)
            flush()
            cur = list(tail)
            w = sum(x.w for x in cur)
            last_break = -1
            continue
        flush()
    if cur:
        flush(hard=True)
    return [ln for ln in lines] or [([], 0.0, True)]


# ----------------------------------------------------------------------
# Lines
# ----------------------------------------------------------------------

class Line(object):
    """One horizontal slice of the flow, with ops in line space."""

    __slots__ = ("h", "ops", "group", "keep", "soft", "para", "brk", "tag",
                 "head_lines")

    def __init__(self, h, ops=None, group=None, keep=False, soft=False,
                 para=None, brk=False, tag="", head_lines=None):
        self.h = int(round(h))
        self.ops = ops or []
        self.group = group
        self.keep = keep          # keep with the line after this one
        self.soft = soft          # drop when it lands at the top of a page
        self.para = para          # paragraph id, for widow control
        self.brk = brk            # force a new page here
        self.tag = tag
        self.head_lines = head_lines   # table header, repeated on new pages


def line_from(atoms_line, face_h, x0, width, align, is_last, ink_default=0):
    """Turn one broken line into drawing ops."""
    atoms, w, hard = atoms_line
    ops = []
    gaps = 0
    extra = 0.0
    if align == "center":
        x0 = x0 + max(0.0, (width - w) / 2.0)
    elif align == "right":
        x0 = x0 + max(0.0, width - w)
    if align == "justify" and not (is_last or hard) and len(atoms) > 1:
        spaces = [i for i, a in enumerate(atoms[1:], 1) if a.kind == "space"]
        breaks = [i for i in range(1, len(atoms))
                  if _can_break(atoms[i - 1], atoms[i])]
        gaps = len(spaces) or len(breaks)
        room = width - w
        if gaps and 0 < room <= gaps * max(3.0, face_h * 0.45):
            extra = room / float(gaps)
        else:
            gaps = 0
    x = float(x0)
    for i, a in enumerate(atoms):
        if a.kind == "br":
            continue
        seg_x = x
        for text, font in a.face.segs(a.text):
            ops.append(("t", int(round(seg_x)), 0, text, font, a.ink))
            seg_x += font.getlength(text)
        adv = a.w
        if gaps and i > 0:
            if (atoms[i].kind == "space") or \
               (not any(b.kind == "space" for b in atoms) and
                    _can_break(atoms[i - 1], a)):
                adv += extra
        if a.under:
            ops.append(("r", int(x), 2, int(x + a.w), 3, a.ink))
        if a.strike:
            ops.append(("r", int(x), -int(face_h * 0.3),
                        int(x + a.w), -int(face_h * 0.3) + 1, a.ink))
        x += adv
    return ops, x - x0


# ----------------------------------------------------------------------
# Blocks -> lines
# ----------------------------------------------------------------------

class Flow(object):
    def __init__(self, theme, book, base_dir="."):
        self.theme = theme
        self.book = book
        self.base_dir = base_dir
        self.lines = []
        self.headings = []        # (level, text, line index)
        self._group = 0
        self._para = 0

    # -- helpers -------------------------------------------------------

    def gap(self, h, soft=True):
        if h > 0:
            self.lines.append(Line(h, soft=soft))

    def next_group(self):
        self._group += 1
        return self._group

    def text_lines(self, frags, size, x0, width, bold=False, italic=False,
                   align=None, first_indent=0, rest_indent=0, ink=None,
                   role="body", face=None, line_h=None, para=None):
        th = self.theme
        book = self.book
        f = face or book.face(role, size, bold, italic)
        atoms = atomize(frags, book, th, size, bold, italic, ink, role)
        broken = break_lines(atoms, width, first_indent, rest_indent)
        lh = line_h or th.body_h(size)
        base = int(round((lh - (f.ascent + f.descent)) / 2.0)) + f.ascent
        out = []
        for i, bl in enumerate(broken):
            indent = first_indent if i == 0 else rest_indent
            ops, _w = line_from(bl, size, x0 + indent, width - indent,
                                align or th.align, i == len(broken) - 1,
                                ink if ink is not None else th.ink)
            ops = [(op[0], op[1], op[2] + base) + op[3:] if op[0] == "t"
                   else _shift_y(op, base) for op in ops]
            out.append(Line(lh, ops, para=para))
        return out

    # -- blocks --------------------------------------------------------

    def add_document(self, blocks):
        prev = None
        for b in blocks:
            self.add_block(b, prev)
            prev = b

    def add_block(self, b, prev=None):
        th = self.theme
        x0 = th.ml
        width = th.content_w
        qdx = b.quote * th.quote_indent
        start = len(self.lines)

        if b.kind == "pagebreak":
            self.lines.append(Line(0, brk=True))
            return

        if b.kind == "heading":
            self.heading(b, x0, width)
        elif b.kind == "rule":
            self.rule(x0, width)
        elif b.kind == "code":
            self.code(b, x0 + qdx, width - qdx)
        elif b.kind == "table":
            self.table(b, x0 + qdx, width - qdx)
        elif b.kind == "image":
            self.image(b, x0 + qdx, width - qdx)
        elif b.kind == "item":
            self.item(b, x0 + qdx, width - qdx)
        else:
            self.para(b, x0 + qdx, width - qdx, prev)

        if b.quote:
            self.decorate_quote(start, b.quote)

    def para(self, b, x0, width, prev=None):
        th = self.theme
        self.gap(max(2, th.para_gap // 3) if b.tight else th.para_gap)
        pid = self._para = self._para + 1
        self.lines.extend(self.text_lines(b.frags, th.size, x0, width,
                                          para=pid))

    def item(self, b, x0, width):
        th = self.theme
        self.gap(max(2, th.para_gap // 3) if b.tight else th.para_gap)
        depth = max(1, b.indent)
        pad = (depth - 1) * th.list_indent
        marker = b.marker or "•"
        face = self.book.face("body", th.size)
        task = marker in ("☐", "☑")
        mw = th.size * 1.15 if task else face.length(marker + " ")
        mw = max(mw, th.size * 0.62)
        pid = self._para = self._para + 1
        lines = self.text_lines(b.frags, th.size, x0 + pad, width - pad,
                                first_indent=mw, rest_indent=mw, para=pid,
                                align="left" if task else None)
        if not lines:
            lines = [Line(th.body_h())]
        lh = lines[0].h
        base = int(round((lh - (face.ascent + face.descent)) / 2.0)) + \
            face.ascent
        if task:
            s = int(th.size * 0.68)
            bx = x0 + pad
            top = base - int(s * 0.92)
            ops = [("b", bx, top, bx + s, top + s, th.ink, 1)]
            if marker == "☑":
                cw = max(1, s // 6)
                ops.append(("l", bx + int(s * 0.24), top + int(s * 0.52),
                            bx + int(s * 0.44), top + int(s * 0.72),
                            th.ink, cw))
                ops.append(("l", bx + int(s * 0.44), top + int(s * 0.72),
                            bx + int(s * 0.78), top + int(s * 0.26),
                            th.ink, cw))
            lines[0].ops = ops + lines[0].ops
        else:
            segs = []
            mx = float(x0 + pad)
            for text, font in face.segs(marker):
                segs.append(("t", int(round(mx)), base, text, font, th.ink))
                mx += font.getlength(text)
            lines[0].ops = segs + lines[0].ops
        self.lines.extend(lines)

    def heading(self, b, x0, width):
        th = self.theme
        lvl = min(6, max(1, b.level))
        size = int(round(th.size * th.h_scale[lvl - 1]))
        if th.chapter_break and lvl == 1 and self.lines:
            self.lines.append(Line(0, brk=True))
        else:
            self.gap(int(round(th.size * (1.5 if lvl <= 2 else 1.1))))
        lines = self.text_lines(b.frags, size, x0, width, bold=True,
                                align="left", line_h=int(round(size * 1.28)))
        if lvl <= 2:
            y = lines[-1].h - 2
            lines[-1].ops.append(("r", x0, y, x0 + width, y + 1,
                                  th.rule_ink if lvl == 2 else th.ink))
            lines[-1].h += 6
        for ln in lines:
            ln.keep = True
            ln.tag = "heading"
        idx = len(self.lines)
        self.lines.extend(lines)
        self.lines.append(Line(max(3, int(th.size * 0.35)), keep=True,
                               tag="heading-gap"))
        if b.anchor:
            self.headings.append((lvl, b.anchor, idx))

    def rule(self, x0, width):
        th = self.theme
        h = max(9, int(th.size * 0.9))
        w = min(width, int(width * 0.55))
        cx = x0 + (width - w) // 2
        self.gap(th.para_gap)
        self.lines.append(Line(h, [("r", cx, h // 2, cx + w, h // 2 + 1,
                                    th.rule_ink)]))

    def code(self, b, x0, width):
        th = self.theme
        size = max(9, int(round(th.size * th.mono_ratio)))
        face = self.book.face("mono", size)
        lh = int(round(size * 1.32))
        pad = th.code_pad
        inner = width - 2 * pad - 2
        base = int(round((lh - (face.ascent + face.descent)) / 2.0)) + \
            face.ascent
        self.gap(th.para_gap)
        rows = []
        for raw in b.lines:
            text = raw.rstrip()
            if not text:
                rows.append(("", False))
                continue
            if face.length(text) <= inner:
                rows.append((text, False))
                continue
            cont_indent = len(text) - len(text.lstrip()) + 2
            first = True
            while text:
                lo, hi, best = 1, len(text), 1
                prefix = "" if first else " " * cont_indent
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if face.length(prefix + text[:mid]) <= inner:
                        best = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                cut = best
                if cut < len(text):
                    sp = text.rfind(" ", 1, cut + 1)
                    if sp > cut * 0.55:
                        cut = sp
                piece = text[:cut] if first else prefix + text[:cut]
                rows.append((piece.rstrip(), not first))
                text = text[cut:].lstrip() if cut < len(text) else ""
                first = False
        shade = 232 if th.four else 255
        n = len(rows)
        for i, (text, _cont) in enumerate(rows):
            h = lh + (pad if i == 0 else 0) + (pad if i == n - 1 else 0)
            y = base + (pad if i == 0 else 0)
            ops = []
            if th.four:
                ops.append(("f", x0, 0, x0 + width, h, shade))
            ops.append(("r", x0, 0, x0 + 2, h, th.rule_ink))
            if not th.four:
                ops.append(("r", x0 + width - 1, 0, x0 + width, h,
                            th.rule_ink))
                if i == 0:
                    ops.append(("r", x0, 0, x0 + width, 1, th.rule_ink))
                if i == n - 1:
                    ops.append(("r", x0, h - 1, x0 + width, h, th.rule_ink))
            tx = float(x0 + pad + 3)
            for seg, font in face.segs(text):
                ops.append(("t", int(round(tx)), y, seg, font, th.ink))
                tx += font.getlength(seg)
            self.lines.append(Line(h, ops, tag="code"))

    def image(self, b, x0, width):
        th = self.theme
        img = load_image(b.src, self.base_dir)
        if img is None:
            frags = [_TextFrag("[그림 %s]" % (b.alt or
                                             os.path.basename(b.src)))]
            self.gap(th.para_gap)
            self.lines.extend(self.text_lines(frags, th.size, x0, width,
                                              italic=True, align="left",
                                              ink=th.muted))
            return
        max_h = int(th.content_h * th.image_max)
        iw, ih = img.size
        scale = min(width / float(iw), max_h / float(ih), 4.0)
        if scale < 1.0 or (scale > 1.0 and iw < width * 0.45):
            nw = max(1, int(iw * scale))
            nh = max(1, int(ih * scale))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        img = dither(img, th.four)
        self.gap(th.para_gap)
        dx = x0 + max(0, (width - img.width) // 2)
        self.lines.append(Line(img.height, [("i", dx, 0, img)],
                               group=self.next_group()))
        if b.alt:
            cap = int(round(th.size * 0.82))
            self.lines.append(Line(max(4, cap // 3)))
            self.lines.extend(self.text_lines(
                [_TextFrag(b.alt)], cap, x0, width, italic=True,
                align="center", ink=th.muted))

    def table(self, b, x0, width):
        th = self.theme
        size = th.size
        head = b.head or []
        rows = b.rows or []
        ncol = max([len(head)] + [len(r) for r in rows] or [1]) or 1
        pad = 5
        face = self.book.face("body", size)
        bold = self.book.face("body", size, bold=True)

        def cell_frags(row, i):
            return row[i] if i < len(row) else []

        self._cur_align = b.align or []

        # Column widths are worked out on the text, then the padding and
        # the grid lines are added, so the table lands exactly on `width`.
        nat = [0.0] * ncol
        mini = [0.0] * ncol
        for row, f in [(head, bold)] + [(r, face) for r in rows]:
            if not row:
                continue
            for i in range(ncol):
                txt = "".join(fr.text for fr in cell_frags(row, i)).strip()
                if not txt:
                    continue
                nat[i] = max(nat[i], f.length(txt))
                words = txt.split() or [txt]
                longest = max(f.length(w) for w in words)
                # CJK breaks between characters, so a few of them is enough
                mini[i] = max(mini[i], min(longest, f.length("가나다가나")))
        for i in range(ncol):
            nat[i] = max(nat[i], size * 1.2)
            mini[i] = max(min(mini[i], nat[i]), size * 1.2)

        avail = width - (ncol + 1) - 2 * pad * ncol
        if avail < ncol * size:
            pad = 2
            avail = width - (ncol + 1) - 2 * pad * ncol
        total = sum(nat)
        if total <= avail:
            slack = avail - total
            cols = [n + slack * (n / total if total else 1.0 / ncol)
                    for n in nat]
        elif sum(mini) >= avail:
            k = avail / sum(mini)
            cols = [m * k for m in mini]
        else:
            spare = avail - sum(mini)
            want = [nat[i] - mini[i] for i in range(ncol)]
            tw = sum(want) or 1.0
            cols = [mini[i] + spare * want[i] / tw for i in range(ncol)]
        cols = [c + 2 * pad for c in cols]

        self.gap(th.para_gap)
        head_lines = self._table_row(head, cols, x0, size, True, pad, True) \
            if head else []
        for ln in head_lines:
            ln.tag = "thead"
            ln.keep = True          # never leave the header alone at the foot
        self.lines.extend(head_lines)
        for r in rows:
            body = self._table_row(r, cols, x0, size, False, pad, False)
            for ln in body:
                ln.head_lines = head_lines
            self.lines.extend(body)

    def _table_row(self, row, cols, x0, size, is_head, pad, top_border):
        th = self.theme
        book = self.book
        face = book.face("body", size, bold=is_head)
        lh = th.body_h(size)
        base = int(round((lh - (face.ascent + face.descent)) / 2.0)) + \
            face.ascent
        cells = []
        for i, cw in enumerate(cols):
            frags = row[i] if i < len(row) else []
            atoms = atomize(frags, book, th, size, is_head, False, th.ink)
            cells.append(break_lines(atoms, max(8.0, cw - 2 * pad)))
        n = max(1, max(len(c) for c in cells))
        group = self.next_group()
        out = []
        for r in range(n):
            h = lh + (pad if r == 0 else 0) + (pad if r == n - 1 else 0)
            y = base + (pad if r == 0 else 0)
            ops = []
            x = float(x0)
            for i, cw in enumerate(cols):
                cx = x + pad
                if r < len(cells[i]):
                    atoms, w, _hard = cells[i][r]
                    al = "center" if is_head else self._t_align(i)
                    off = 0.0
                    inner = cw - 2 * pad
                    if al == "center":
                        off = max(0.0, (inner - w) / 2.0)
                    elif al == "right":
                        off = max(0.0, inner - w)
                    ax = cx + off
                    for a in atoms:
                        for seg, font in a.face.segs(a.text):
                            ops.append(("t", int(round(ax)), y, seg, font,
                                        a.ink))
                            ax += font.getlength(seg)
                ops.append(("r", int(x), 0, int(x) + 1, h, th.rule_ink))
                x += cw
            ops.append(("r", int(x), 0, int(x) + 1, h, th.rule_ink))
            if r == 0 and top_border:
                ops.append(("r", x0, 0, int(x) + 1, 1, th.rule_ink))
            if r == n - 1:
                ops.append(("r", x0, h - 1, int(x) + 1, h, th.rule_ink))
            out.append(Line(h, ops, group=group))
        return out

    def _t_align(self, i):
        al = getattr(self, "_cur_align", None) or []
        return al[i] if i < len(al) else "left"

    def decorate_quote(self, start, depth):
        th = self.theme
        for ln in self.lines[start:]:
            if ln.h <= 0:
                continue
            for d in range(depth):
                x = th.ml + d * th.quote_indent + 2
                ln.ops.insert(0, ("r", x, 0, x + 2, ln.h, th.rule_ink))


class _TextFrag(object):
    __slots__ = ("text", "bold", "italic", "mono", "strike", "link", "br")

    def __init__(self, text):
        self.text = text
        self.bold = self.italic = self.mono = self.strike = False
        self.link = None
        self.br = False


def _shift_y(op, dy):
    k = op[0]
    if k in ("r", "l", "f", "b"):
        return (k, op[1], op[2] + dy, op[3], op[4] + dy) + op[5:]
    if k == "i":
        return ("i", op[1], op[2] + dy, op[3])
    return op


# ----------------------------------------------------------------------
# Pictures
# ----------------------------------------------------------------------

_BAYER = None


def _bayer8():
    global _BAYER
    if _BAYER is None:
        import numpy as np
        m = np.array([[0, 32, 8, 40, 2, 34, 10, 42],
                      [48, 16, 56, 24, 50, 18, 58, 26],
                      [12, 44, 4, 36, 14, 46, 6, 38],
                      [60, 28, 52, 20, 62, 30, 54, 22],
                      [3, 35, 11, 43, 1, 33, 9, 41],
                      [51, 19, 59, 27, 49, 17, 57, 25],
                      [15, 47, 7, 39, 13, 45, 5, 37],
                      [63, 31, 55, 23, 61, 29, 53, 21]], dtype="float32")
        _BAYER = (m + 0.5) / 64.0
    return _BAYER


def load_image(src, base_dir):
    if not src:
        return None
    if src.startswith("data:"):
        try:
            import base64
            head, b64 = src.split(",", 1)
            if "base64" not in head:
                return None
            import io
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("L")
        except Exception:
            return None
    if re.match(r"^[a-z]+://", src):
        return None
    path = src if os.path.isabs(src) else os.path.join(base_dir, src)
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return None
    try:
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        return im.convert("L")
    except Exception:
        return None


def dither(img, four_level):
    """Grey picture -> pixels the screen can show, still in mode L."""
    import numpy as np
    if four_level:
        a = np.asarray(img, dtype="float32") / 255.0 * 3.0
        h, w = a.shape
        t = np.tile(_bayer8(), ((h + 7) // 8, (w + 7) // 8))[:h, :w]
        lv = np.clip(np.round(a + (t - 0.5)), 0, 3).astype("uint8")
        return Image.fromarray((lv * 85).astype("uint8"), "L")
    return img.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------

def paginate(lines, theme):
    """Fill pages: keep headings with their text, rows whole, no widows."""
    pages = []
    cur = []
    y = 0
    limit = theme.content_h
    n = len(lines)
    i = 0

    def run_len(j):
        """How many lines from j on belong to the same paragraph."""
        if j >= n or lines[j].para is None:
            return 0
        p = lines[j].para
        k = j
        while k < n and lines[k].para == p:
            k += 1
        return k - j

    def chunk_at(j):
        """Lines that must sit on one page together, starting at j."""
        out = [j]
        if lines[j].group is not None:
            k = j + 1
            while k < n and lines[k].group == lines[j].group:
                out.append(k)
                k += 1
        k = out[-1]
        while lines[k].keep and k + 1 < n:
            k += 1
            out.append(k)
            if lines[k].group is not None:
                while k + 1 < n and lines[k + 1].group == lines[k].group:
                    k += 1
                    out.append(k)
            if sum(lines[m].h for m in out) > limit:
                break
        # a heading wants two lines of its text under it, not one
        if any(lines[m].tag.startswith("heading") for m in out):
            k = out[-1]
            if k + 1 < n and lines[k + 1].para is not None and \
                    lines[k + 1].para == lines[k].para:
                if sum(lines[m].h for m in out) + lines[k + 1].h <= limit:
                    out.append(k + 1)
        return out

    def close():
        """End the page, pushing widowed lines to the next one."""
        nonlocal cur, i
        keep_back = list(cur)
        back = 0
        while len(cur) > 1:
            last = cur[-1][0]
            if last.para is None:
                break
            if i >= n or lines[i].para != last.para:
                break                       # paragraph ends on this page
            here = sum(1 for ln, _ in cur if ln.para == last.para)
            rest = run_len(i)
            if here >= 2 and rest >= 2:
                break                       # a clean split
            if back >= 3:
                break
            cur.pop()
            i -= 1
            back += 1
            while len(cur) > 1 and cur[-1][0].keep:
                cur.pop()
                i -= 1
                back += 1
        if not cur:
            cur = keep_back
            i += back
        pages.append([ln for ln in cur])
        cur = []

    while i < n:
        ln = lines[i]
        if ln.brk:
            if cur:
                close()
                y = 0
            i += 1
            continue
        if ln.soft and not cur:
            i += 1
            continue
        idx = chunk_at(i)
        h = sum(lines[k].h for k in idx)
        head = ln.head_lines if not cur else None
        if head:
            h += sum(hl.h for hl in head)
        if cur and y + h > limit:
            close()
            y = 0
            continue
        if head:
            # the table goes on: draw its header again at the top
            for hl in head:
                cur.append((hl, y))
                y += hl.h
        for k in idx:
            cur.append((lines[k], y))
            y += lines[k].h
        i = idx[-1] + 1
        if y >= limit and i < n:
            close()
            y = 0
    if cur:
        pages.append(list(cur))
    return [_restack(p) for p in pages if p]


def _restack(page):
    """Re-run the y positions after lines were moved between pages."""
    out = []
    y = 0
    for ln, _old in page:
        out.append((ln, y))
        y += ln.h
    return out


def paint_page(page, theme, page_no=None, total=None):
    """Play the ops of one page onto a grey sheet."""
    img = Image.new("L", (theme.w, theme.h), 255)
    d = ImageDraw.Draw(img)
    if not theme.four:
        d.fontmode = "1"
    top = theme.mt
    for line, y in page:
        oy = top + y
        for op in line.ops:
            k = op[0]
            if k == "t":
                _, x, ty, text, font, ink = op
                d.text((x, oy + ty), text, font=font, fill=ink, anchor="ls")
            elif k == "r":
                _, x0, y0, x1, y1, ink = op
                d.rectangle([x0, oy + y0, max(x0, x1 - 1),
                             oy + max(y0, y1 - 1)], fill=ink)
            elif k == "f":
                _, x0, y0, x1, y1, shade = op
                d.rectangle([x0, oy + y0, x1 - 1, oy + y1 - 1], fill=shade)
            elif k == "l":
                _, x0, y0, x1, y1, ink, w = op
                d.line([x0, oy + y0, x1, oy + y1], fill=ink, width=w)
            elif k == "b":
                _, x0, y0, x1, y1, ink, w = op
                d.rectangle([x0, oy + y0, x1, oy + y1], outline=ink, width=w)
            elif k == "i":
                _, x, iy, im = op
                img.paste(im, (x, oy + iy))
    if theme.footer and page_no:
        f = _footer_face(theme)
        text = "%d" % page_no
        w = f.length(text)
        x = (theme.w - w) / 2.0
        y = theme.h - theme.mb + theme.footer_size
        for seg, font in f.segs(text):
            d.text((int(round(x)), int(y)), seg, font=font,
                   fill=theme.muted, anchor="ls")
            x += font.getlength(seg)
    return img


def _footer_face(theme):
    return theme.book.face("body", theme.footer_size)


def page_to_bits(img, theme, cfg):
    """Sheet -> the numbers the XTC encoders want."""
    import numpy as np
    if cfg.landscape:
        img = img.rotate(90 if cfg.turn_right else -90, expand=True)
    a = np.asarray(img, dtype="uint8")
    if theme.four:
        return np.clip((a.astype("uint16") + 42) // 85, 0, 3).astype("uint8")
    return (a > 127).astype("uint8")


def make_cover(theme, book, title, author):
    """A plain title page."""
    img = Image.new("L", (theme.w, theme.h), 255)
    d = ImageDraw.Draw(img)
    if not theme.four:
        d.fontmode = "1"
    size = int(theme.size * 2.0)
    face = book.face("body", size, bold=True)
    width = theme.content_w
    frags = [_TextFrag(title or "")]
    atoms = atomize(frags, book, theme, size, True, False, theme.ink)
    lines = break_lines(atoms, width)
    lh = int(size * 1.32)
    total = len(lines) * lh
    y = int(theme.h * 0.34) - total // 2
    for bl in lines:
        atoms_, w, _h = bl
        x = theme.ml + (width - w) / 2.0
        for a in atoms_:
            for seg, font in a.face.segs(a.text):
                d.text((int(round(x)), y + face.ascent), seg, font=font,
                       fill=theme.ink, anchor="ls")
                x += font.getlength(seg)
        y += lh
    y += int(theme.size * 0.9)
    d.rectangle([theme.ml + width // 3, y, theme.ml + width - width // 3,
                 y + 1], fill=theme.rule_ink)
    if author:
        y += int(theme.size * 1.6)
        asize = int(theme.size * 1.05)
        aface = book.face("body", asize)
        atoms = atomize([_TextFrag(author)], book, theme, asize, False, False,
                        theme.ink)
        for bl in break_lines(atoms, width):
            atoms_, w, _h = bl
            x = theme.ml + (width - w) / 2.0
            for a in atoms_:
                for seg, font in a.face.segs(a.text):
                    d.text((int(round(x)), y + aface.ascent), seg, font=font,
                           fill=theme.ink, anchor="ls")
                    x += font.getlength(seg)
            y += int(asize * 1.4)
    return img


def toc_lines(entries, theme, book, offset):
    """Contents pages: heading text on the left, page number on the right."""
    out = []
    size = theme.size
    face = book.face("body", size)
    lh = theme.body_h(size)
    for level, text, page in entries:
        f = book.face("body", size, bold=(level == 1))
        base = int(round((lh - (f.ascent + f.descent)) / 2.0)) + f.ascent
        indent = (level - 1) * int(theme.size * 0.9)
        x0 = theme.ml + indent
        num = "%d" % (page + offset)
        nw = face.length(num)
        avail = theme.content_w - indent - nw - 8
        atoms = atomize([_TextFrag(text)], book, theme, size,
                        level == 1, False, theme.ink)
        broken = break_lines(atoms, avail)
        atoms_, w, _h = broken[0]
        if len(broken) > 1:
            atoms_ = atoms_ + [Atom("…", f, theme.ink, False, False, "word")]
            w += f.length("…")
        ops = []
        x = float(x0)
        for a in atoms_:
            for seg, font in a.face.segs(a.text):
                ops.append(("t", int(round(x)), base, seg, font, theme.ink))
                x += font.getlength(seg)
        dot_x0 = int(x + 4)
        dot_x1 = int(theme.ml + theme.content_w - nw - 4)
        if dot_x1 > dot_x0:
            ops.append(("r", dot_x0, base - 3, dot_x1, base - 2, theme.muted))
        nx = theme.ml + theme.content_w - nw
        for seg, font in face.segs(num):
            ops.append(("t", int(round(nx)), base, seg, font, theme.ink))
            nx += font.getlength(seg)
        out.append(Line(lh, ops))
    return out
