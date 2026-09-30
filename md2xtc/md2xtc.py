# -*- coding: utf-8 -*-
"""
Markdown -> XTC converter for Xteink readers.

The markdown is laid out the way a preview shows it -- headings, lists,
quotes, code, tables, pictures -- but at the size of the reader screen,
so nothing has to be shrunk down afterwards. Each screenful becomes one
picture, and all the pictures go into one .xtc file.

    python3 md2xtc.py book.md
    python3 md2xtc.py notes/ --png preview/
    python3 md2xtc.py book.md --4 --size 19 --toc
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "_lib")
if os.path.isdir(LIB) and LIB not in sys.path:
    sys.path.insert(0, LIB)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import xtc                                                     # noqa: E402

MD_EXT = (".md", ".markdown", ".mdown", ".mkd", ".mdtxt", ".text")


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------

DEFAULTS = {
    "width": "480",
    "height": "800",
    "color": "1bit",
    "font": "serif",
    "font_size": "17",
    "line_spacing": "1.55",
    "para_spacing": "0.55",
    "margin": "26",
    "margin_top": "",
    "margin_bottom": "",
    "align": "left",
    "page_numbers": "on",
    "chapter_break": "off",
    "cover": "auto",
    "toc": "off",
    "toc_depth": "2",
    "show_urls": "off",
    "images": "on",
    "orientation": "portrait",
    "turn": "right",
    "language": "ko-KR",
    "layout": "compat",
    "line_break": "char",
    "toc_title": "auto",
    "notes_title": "auto",
    "breaks": "off",
}

# The settings file may use Korean names, like the PDF converter does.
ALIASES = {
    "가로": "width", "세로": "height", "색": "color", "글꼴": "font",
    "글자크기": "font_size", "줄간격": "line_spacing",
    "문단간격": "para_spacing", "여백": "margin", "위여백": "margin_top",
    "아래여백": "margin_bottom", "정렬": "align", "쪽번호": "page_numbers",
    "장나눔": "chapter_break", "표지": "cover", "목차": "toc",
    "목차깊이": "toc_depth", "링크주소": "show_urls", "그림": "images",
    "화면방향": "orientation", "가로돌림": "turn", "언어": "language",
    "파일구조": "layout", "줄바꿈": "line_break", "목차이름": "toc_title",
    "주석이름": "notes_title",
}

OFF = ("off", "no", "0", "false", "끔", "끄기", "아니오", "없음")
ON = ("on", "yes", "1", "true", "켬", "켜기", "예", "있음")

SETTINGS_FILES = ("settings.txt", "설정.txt")


def load_settings(folder=HERE):
    s = dict(DEFAULTS)
    for name in SETTINGS_FILES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        raw = open(path, "rb").read()
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            continue
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = ALIASES.get(k.strip(), k.strip().lower().replace(" ", "_"))
            v = v.strip()
            if k in s and v:
                s[k] = v
    return s


def _num(v, default, lo=None, hi=None, real=False):
    try:
        x = float(str(v).replace(",", ".")) if real else \
            int(re.sub(r"[^\d-]", "", str(v)) or default)
    except (TypeError, ValueError):
        x = default
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def _flag(v, default=True):
    t = str(v).strip().lower()
    if t in OFF:
        return False
    if t in ON:
        return True
    return default


class Config(object):
    def __init__(self, s):
        self.width = _num(s["width"], 480, 32, 4000)
        self.height = _num(s["height"], 800, 32, 4000)
        self.four_level = "4" in str(s["color"])
        fam = str(s["font"]).strip().lower()
        self.font_family = "sans" if fam in ("sans", "고딕", "gothic",
                                             "sans-serif") else "serif"
        self.font_size = _num(s["font_size"], 17, 8, 96)
        self.line_spacing = _num(s["line_spacing"], 1.55, 1.0, 3.0, real=True)
        self.para_spacing = _num(s["para_spacing"], 0.55, 0.0, 3.0, real=True)
        self.margin = _num(s["margin"], 26, 0, 200)
        self.margin_top = _num(s["margin_top"], -1, -1, 200) \
            if str(s["margin_top"]).strip() else -1
        self.margin_bottom = _num(s["margin_bottom"], -1, -1, 200) \
            if str(s["margin_bottom"]).strip() else -1
        al = str(s["align"]).strip().lower()
        self.align = "justify" if al in ("justify", "both", "양쪽",
                                         "양끝") else "left"
        self.page_numbers = _flag(s["page_numbers"], True)
        self.chapter_break = _flag(s["chapter_break"], False)
        self.cover = str(s["cover"]).strip().lower()
        self.toc = _flag(s["toc"], False)
        self.toc_depth = _num(s["toc_depth"], 2, 1, 6)
        self.show_urls = _flag(s["show_urls"], False)
        self.images = _flag(s["images"], True)
        self.image_max = 0.82
        self.landscape = str(s["orientation"]).strip().lower() in (
            "landscape", "가로", "wide")
        self.turn_right = "왼" not in str(s["turn"]) and \
            str(s["turn"]).strip().lower() != "left"
        self.language = str(s["language"]).strip() or "ko-KR"
        self.layout = "spec" if str(s["layout"]).strip().lower() in (
            "spec", "규격", "metadata") else "compat"
        self.line_break = "word" if str(s["line_break"]).strip().lower() in (
            "word", "낱말", "어절", "단어") else "char"
        self.toc_title = str(s["toc_title"]).strip()
        self.notes_title = str(s["notes_title"]).strip()
        self.breaks = _flag(s["breaks"], False)

    def canvas(self):
        """Sheet size before it is turned. Wide when the screen is held
        sideways."""
        if self.landscape:
            return self.height, self.width
        return self.width, self.height


# ----------------------------------------------------------------------
# Parts check
# ----------------------------------------------------------------------

def check_parts(quiet=False):
    missing = []
    for name, pip in (("PIL", "pillow"), ("numpy", "numpy"),
                      ("markdown_it", "markdown-it-py")):
        try:
            __import__(name)
        except ImportError:
            missing.append(pip)
    if missing and not quiet:
        print("[!] 필요한 부품이 없습니다: " + ", ".join(missing))
        print("    pip install " + " ".join(missing))
    return missing


# ----------------------------------------------------------------------
# Conversion
# ----------------------------------------------------------------------

def _title_author(path, doc):
    title = doc.title or os.path.splitext(os.path.basename(path))[0]
    author = doc.author
    if not author:
        m = re.match(r"^(.*?)\s*[-–]\s*(.+)$", title)
        if m and len(m.group(2)) <= 30:
            title, author = m.group(1).strip(), m.group(2).strip()
    return title, author


def convert(paths, cfg, out_path=None, png_dir=None, title=None,
            author=None):
    """One or more markdown files -> one .xtc file."""
    import mdmodel
    import typeset

    opts = {"show_urls": cfg.show_urls, "notes_title": cfg.notes_title,
            "breaks": cfg.breaks}

    docs = []
    for p in paths:
        docs.append(mdmodel.read_markdown(p, opts))

    first = docs[0]
    t, a = _title_author(paths[0], first)
    title = title or t
    author = author or a

    theme = typeset.Theme(cfg)
    book = typeset.FontBook(cfg.font_family)
    theme.book = book

    flow = typeset.Flow(theme, book, first.base_dir)
    for i, doc in enumerate(docs):
        flow.base_dir = doc.base_dir
        blocks = doc.blocks
        if not cfg.images:
            blocks = [b for b in blocks if b.kind != "image"]
        if i:
            flow.lines.append(typeset.Line(0, brk=True))
        flow.add_document(blocks)

    if not flow.lines:
        raise ValueError("내용이 없습니다")

    body = typeset.paginate(flow.lines, theme)

    # where did each heading land
    line_page = {}
    for pno, page in enumerate(body):
        for ln, _y in page:
            line_page[id(ln)] = pno
    entries = []
    for level, text, idx in flow.headings:
        if level > cfg.toc_depth or idx >= len(flow.lines):
            continue
        p = line_page.get(id(flow.lines[idx]))
        if p is not None:
            entries.append((level, text, p))

    # "auto" means: a title page when the file says its title in the
    # front matter. Anything else is the user's call.
    want_cover = cfg.cover in ("on", "yes", "1", "true", "켬", "켜기", "예") \
        or (cfg.cover in ("auto", "자동") and first.meta_title)
    cover_pages = 1 if want_cover else 0

    toc_pages = []
    if cfg.toc and entries:
        name = cfg.toc_title
        if not name or name.lower() in ("auto", "자동"):
            sample = " ".join(t for _l, t, _p in entries)
            name = "목차" if re.search(r"[\uac00-\ud7ff]", sample) else \
                "Contents"
        lines = _toc_flow(entries, theme, book, 0, name)
        toc_pages = typeset.paginate(lines, theme)
        offset = cover_pages + len(toc_pages) + 1
        lines = _toc_flow(entries, theme, book, offset, name)
        toc_pages = typeset.paginate(lines, theme)

    offset = cover_pages + len(toc_pages)
    total = offset + len(body)

    pages = []
    sheets = []
    if want_cover:
        sheets.append((typeset.make_cover(theme, book, title, author), None))
    for i, page in enumerate(toc_pages):
        sheets.append((typeset.paint_page(page, theme, cover_pages + i + 1,
                                          total), cover_pages + i + 1))
    for i, page in enumerate(body):
        sheets.append((typeset.paint_page(page, theme, offset + i + 1, total),
                       offset + i + 1))

    if png_dir and not os.path.isdir(png_dir):
        os.makedirs(png_dir)

    for i, (img, _n) in enumerate(sheets):
        buf = typeset.page_to_bits(img, theme, cfg)
        if cfg.four_level:
            pages.append(xtc.encode_xth(buf, cfg.width, cfg.height))
        else:
            pages.append(xtc.encode_xtg(buf, cfg.width, cfg.height))
        if png_dir:
            # the preview shows the very pixels the reader will show
            from PIL import Image as _Im
            step = 85 if cfg.four_level else 255
            _Im.fromarray((buf * step).astype("uint8"), "L").save(
                os.path.join(png_dir, "page%04d.png" % (i + 1)))

    if out_path is None:
        ext = ".xtch" if cfg.four_level else ".xtc"
        out_path = os.path.splitext(paths[0])[0] + ext

    blob = xtc.build_container(pages, cfg.width, cfg.height, title=title,
                               author=author, language=cfg.language,
                               high_quality=cfg.four_level,
                               layout=cfg.layout)
    with open(out_path, "wb") as f:
        f.write(blob)

    return {"out": out_path, "pages": len(pages), "body": len(body),
            "toc": len(toc_pages), "cover": cover_pages, "bytes": len(blob),
            "title": title, "author": author, "headings": len(entries),
            "dropped": book.dropped, "missing": book.missing}


def _toc_flow(entries, theme, book, offset, name="목차"):
    """Contents lines with a heading on top."""
    import typeset
    lines = []
    size = int(round(theme.size * 1.48))
    face = book.face("body", size, bold=True)
    lh = int(round(size * 1.35))
    base = int(round((lh - (face.ascent + face.descent)) / 2.0)) + face.ascent
    ops = []
    x = float(theme.ml)
    for seg, font in face.segs(name):
        ops.append(("t", int(x), base, seg, font, theme.ink))
        x += font.getlength(seg)
    ops.append(("r", theme.ml, lh - 2, theme.ml + theme.content_w, lh - 1,
                theme.rule_ink))
    lines.append(typeset.Line(lh + 8, ops))
    lines.append(typeset.Line(max(4, theme.size // 2)))
    lines.extend(typeset.toc_lines(entries, theme, book, offset))
    return lines


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------

def collect(args):
    found = []
    for a in args:
        if os.path.isdir(a):
            for root, _dirs, names in os.walk(a):
                for n in sorted(names):
                    if n.lower().endswith(MD_EXT):
                        found.append(os.path.join(root, n))
        elif os.path.isfile(a) and a.lower().endswith(MD_EXT):
            found.append(a)
        elif os.path.isfile(a):
            found.append(a)          # let the user force any text file
    return found


USAGE = """마크다운 -> XTC 변환기 (Xteink)

  python3 md2xtc.py 파일.md [더 있는 파일 ...] [옵션]

옵션
  -o, --out 파일      나올 .xtc 이름
      --png 폴더      쪽마다 PNG로도 내보낸다 (컴퓨터에서 미리 보기)
      --join          여러 파일을 한 권으로 묶는다
      --width  N      화면 가로 (기본 480)
      --height N      화면 세로 (기본 800)
      --4             4단계 회색으로 (.xtch). 사진이 많을 때.
      --size   N      글자 크기 (기본 17)
      --line   N      줄간격 (기본 1.55)
      --margin N      여백 (기본 26)
      --font   serif|sans
      --align  left|justify
      --toc           목차 쪽을 만든다
      --cover / --no-cover
      --numbers / --no-numbers
      --chapter       # 제목마다 새 쪽에서 시작
      --landscape     화면을 눕혀서 본다
      --spec          규격형 머리말(제목/글쓴이 포함)로 저장
      --title / --author 글자
      --check         부품만 확인하고 끝낸다
"""


def parse_args(argv, s):
    files = []
    out = png = None
    join = False
    quiet = False
    i = 1
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if a in ("-h", "--help"):
            print(USAGE)
            raise SystemExit(0)
        elif a in ("-o", "--out"):
            out = nxt
            i += 1
        elif a == "--png":
            png = nxt
            i += 1
        elif a == "--join":
            join = True
        elif a == "--quiet":
            quiet = True
        elif a == "--width":
            s["width"] = nxt
            i += 1
        elif a == "--height":
            s["height"] = nxt
            i += 1
        elif a in ("--4", "--4level", "--grey", "--gray"):
            s["color"] = "4"
        elif a in ("--1", "--mono"):
            s["color"] = "1bit"
        elif a == "--size":
            s["font_size"] = nxt
            i += 1
        elif a == "--line":
            s["line_spacing"] = nxt
            i += 1
        elif a == "--margin":
            s["margin"] = nxt
            i += 1
        elif a == "--font":
            s["font"] = nxt
            i += 1
        elif a == "--align":
            s["align"] = nxt
            i += 1
        elif a == "--toc":
            s["toc"] = "on"
        elif a == "--no-toc":
            s["toc"] = "off"
        elif a == "--cover":
            s["cover"] = "on"
        elif a == "--no-cover":
            s["cover"] = "off"
        elif a == "--numbers":
            s["page_numbers"] = "on"
        elif a == "--no-numbers":
            s["page_numbers"] = "off"
        elif a == "--chapter":
            s["chapter_break"] = "on"
        elif a == "--landscape":
            s["orientation"] = "landscape"
        elif a == "--urls":
            s["show_urls"] = "on"
        elif a == "--no-images":
            s["images"] = "off"
        elif a == "--spec":
            s["layout"] = "spec"
        elif a == "--title":
            s["_title"] = nxt
            i += 1
        elif a == "--author":
            s["_author"] = nxt
            i += 1
        elif a == "--check":
            pass
        elif a.startswith("-"):
            print("[!] 모르는 옵션: %s" % a)
            raise SystemExit(2)
        else:
            files.append(a)
        i += 1
    return files, out, png, join, quiet


def main(argv):
    s = load_settings()
    if "--check" in argv:
        return 2 if check_parts(quiet=True) else 0

    args, out, png, join, quiet = parse_args(argv, s)
    if check_parts():
        return 1

    cfg = Config(s)
    title = s.get("_title")
    author = s.get("_author")

    if not args:
        args = [os.getcwd()]
        print("[i] 파일을 안 주셔서 이 폴더 안의 마크다운을 찾습니다.")

    targets = collect(args)
    if not targets:
        print("\n[!] 바꿀 .md 파일이 없습니다.\n")
        print(USAGE)
        return 1

    color = "4단계 회색 (.xtch)" if cfg.four_level else "1비트 흑백 (.xtc)"
    way = "가로 (%s쪽으로 눕혀서)" % ("오른" if cfg.turn_right else "왼") \
        if cfg.landscape else "세로"
    if not quiet:
        print("\n화면 %dx%d / %s / %s" % (cfg.width, cfg.height, way, color))
        print("글꼴 %s %dpx / 줄간격 %.2f / 여백 %d / 정렬 %s"
              % (cfg.font_family, cfg.font_size, cfg.line_spacing,
                 cfg.margin, cfg.align))
        print("%d개 파일을 바꿉니다.\n" % (1 if join else len(targets)))

    jobs = [targets] if join else [[t] for t in targets]
    if out and len(jobs) > 1:
        print("[!] --out 은 파일 하나에만 씁니다. 여러 개를 한 권으로 "
              "묶으려면 --join 을 쓰세요.\n")
        return 2
    ok = 0
    for job in jobs:
        name = os.path.basename(job[0]) + (" 외 %d개" % (len(job) - 1)
                                           if len(job) > 1 else "")
        if not quiet:
            print("  [진행] %s" % name)
        try:
            r = convert(job, cfg, out_path=out, png_dir=png, title=title,
                        author=author)
            ok += 1
            if not quiet:
                extra = []
                if r["cover"]:
                    extra.append("표지 1쪽")
                if r["toc"]:
                    extra.append("목차 %d쪽" % r["toc"])
                if r["dropped"]:
                    extra.append("글꼴에 없는 글자 %d개는 빼고 그렸습니다"
                                 % r["dropped"])
                print("  [OK] -> %s" % os.path.basename(r["out"]))
                print("       %d쪽, %.2f MB%s" %
                      (r["pages"], r["bytes"] / 1048576.0,
                       ("  (" + ", ".join(extra) + ")") if extra else ""))
                if png:
                    print("       미리보기 PNG: %s" % png)
                print("")
        except Exception as e:
            print("  [실패] %s: %s\n" % (name, e))
            if os.environ.get("MD2XTC_DEBUG"):
                import traceback
                traceback.print_exc()

    if not quiet:
        print("끝났습니다. 성공 %d / 전체 %d" % (ok, len(jobs)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
