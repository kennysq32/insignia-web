#!/usr/bin/env python3
"""
INSIGNIA — static site builder
==============================

    python3 build.py              build the site into ./dist
    python3 build.py serve        build, serve at http://localhost:8000 and rebuild on every save
    python3 build.py --drafts     also build pages marked `draft: true`

Needs Python 3.9+ with markdown, jinja2 and pyyaml (pip install -r requirements.txt).

Content lives in ./content (Markdown + YAML), page layouts in ./templates,
styles and scripts in ./assets, and images or other files in ./static.
README.md has the writing guide.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import unicodedata
import xml.etree.ElementTree as etree
from contextlib import contextmanager
from datetime import date, datetime
from functools import partial
from html import escape, unescape
from pathlib import Path

import markdown
import yaml
from jinja2 import ChainableUndefined, Environment, FileSystemLoader, TemplateError, select_autoescape
from markdown.extensions import Extension
from markdown.extensions.toc import TocExtension, slugify_unicode
from markdown.inlinepatterns import InlineProcessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor

try:
    import fcntl
except ImportError:                    # Windows: builds are not serialised
    fcntl = None

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
STATIC = ROOT / "static"
DIST = ROOT / "dist"
LOCK = ROOT / ".build.lock"

RESERVED_SLUGS = {"novel", "wiki", "gallery", "films", "assets", "images", "search.json"}


class BuildError(Exception):
    """A problem in the content that the author needs to fix."""


# ─── Small helpers ──────────────────────────────────────────────────────────

def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def norm(text) -> str:
    """Turn a title into a lookup key / URL slug: 'The Dimming' -> 'the-dimming'."""
    text = unicodedata.normalize("NFKC", str(text)).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^\w\-]", "", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def unyaml_link(value):
    """`key: [[Page]]` without quotes is parsed by YAML as a nested list. Undo that."""
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list) and len(value[0]) == 1:
        return f"[[{value[0][0]}]]"
    return value


def strip_tags(html: str) -> str:
    html = re.sub(r"<sup[^>]*>.*?</sup>", "", html, flags=re.S)
    return unescape(re.sub(r"<[^>]+>", "", html))


def truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—–-") + "…"


def first_paragraph(html: str, as_html=False) -> str:
    for m in re.finditer(r"<p>(.*?)</p>", html, re.S):
        text = strip_tags(m.group(1)).strip()
        if text:
            return m.group(1) if as_html else text
    return ""


def first_image(html: str):
    m = re.search(r'<img[^>]+src="([^"]+)"', html)
    return m.group(1) if m else None


CJK = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏一-鿿가-힯]")
LATIN_WORD = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’\-][A-Za-z0-9À-ɏ]+)*")


def reading_minutes(html: str) -> int:
    text = strip_tags(html)
    return max(1, round(len(LATIN_WORD.findall(text)) / 238 + len(CJK.findall(text)) / 500))


def to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def format_date(value, style="medium"):
    d = to_date(value)
    if d is None:
        return value or ""
    if style == "dots":
        return d.strftime("%d.%m.%Y")
    if style == "iso":
        return d.isoformat()
    if style == "long":                      # 27 September 2026 — the Archive
        return f"{d.day} {d.strftime('%B %Y')}"
    if style == "year":
        return str(d.year)
    return f"{d.strftime('%b')} {d.day}, {d.year}"   # Sep 27, 2026 — the reader


HANGUL_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def index_letter(title: str) -> str:
    ch = (title or "#")[0]
    if "가" <= ch <= "힣":
        return HANGUL_INITIALS[(ord(ch) - 0xAC00) // 588]
    return ch.upper() if ch.isalpha() else "#"


def youtube_id(value) -> str:
    value = str(value or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([\w-]{6,20})", value)
    return m.group(1) if m else value


@contextmanager
def build_lock():
    """One build at a time, even across processes (dev server, share, publish)."""
    if fcntl is None:
        yield
        return
    with open(LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def replace_dist(new: Path):
    """Swap a finished build into dist/ with renames, so a running server never sees a half-built site."""
    olds = []
    for attempt in range(10):
        try:
            if DIST.exists():
                old = ROOT / f".dist-old-{os.getpid()}-{attempt}"
                DIST.rename(old)
                olds.append(old)
            new.rename(DIST)
            break
        except OSError:              # another process swapped at the same moment — try again
            time.sleep(0.1)
    else:
        raise BuildError("Could not replace dist/. Is another program using it?")
    for old in olds:
        shutil.rmtree(old, ignore_errors=True)


FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S)


def read_markdown(path: Path):
    text = path.read_text(encoding="utf-8").lstrip("﻿")
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise BuildError(f"{rel(path)}: the front matter (between the --- lines) is not valid YAML.\n{e}") from None
    if not isinstance(meta, dict):
        raise BuildError(f"{rel(path)}: the front matter must be a list of `key: value` lines.")
    return meta, m.group(2)


def load_yaml(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BuildError(f"{rel(path)} is not valid YAML.\n{e}") from None


# ─── Markdown extensions ────────────────────────────────────────────────────

class LinkContext:
    """Remembers which Archive entries a piece of content links to."""

    def __init__(self, builder: "Builder", where: str, self_slug: str | None = None):
        self.builder = builder
        self.where = where
        self.self_slug = self_slug
        self.links: dict[str, None] = {}      # ordered set of slugs
        self._md: dict = {}


WIKILINK_RE = r"\[\[([^\[\]\|\n]+?)(?:\|([^\[\]\n]+?))?\]\]([a-z]+)?"


class WikiLinkPattern(InlineProcessor):
    """[[Entry]], [[Entry|label]], [[Entry#Section]], [[#Section]] and [[Entry]]s."""

    def __init__(self, ctx: LinkContext, md):
        super().__init__(WIKILINK_RE, md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        target, label, trail = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3) or ""
        if target.lower().startswith("youtube:"):
            return None, None, None
        page, _, section = target.partition("#")
        page, section = page.strip(), section.strip()
        anchor = "#" + slugify_unicode(section, "-") if section else ""

        if not page:                                   # [[#Section]] — same page
            el = etree.Element("a", {"href": anchor})
            el.text = label or section
            return el, m.start(0), m.end(0)

        text = (label or (f"{page} § {section}" if section else page)) + trail
        entry = self.ctx.builder.lookup(page)
        if entry is None:
            self.ctx.builder.missing.setdefault(page, set()).add(self.ctx.where)
            el = etree.Element("a", {"class": "wikilink new", "title": f"{page} (not yet written)"})
        elif entry["slug"] == self.ctx.self_slug and not section:
            el = etree.Element("strong", {"class": "selflink"})
        else:
            self.ctx.links[entry["slug"]] = None
            el = etree.Element("a", {"class": "wikilink", "href": entry["url"] + anchor})
        el.text = text
        return el, m.start(0), m.end(0)


PLAY_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l12.5-7.5z" '
             'fill="currentColor"/></svg>')


def youtube_html(video_id: str, caption: str = "", title: str = "") -> str:
    vid, title = escape(video_id), escape(title or caption or "YouTube video")
    cap = f"<figcaption>{escape(caption)}</figcaption>" if caption else ""
    return (
        f'<figure class="yt"><div class="yt-embed" data-yt="{vid}" data-title="{title}">'
        f'<img src="https://i.ytimg.com/vi/{vid}/maxresdefault.jpg" alt="" loading="lazy" data-yt-thumb>'
        f'<button class="yt-play" type="button" aria-label="Play video: {title}">'
        f'<span class="rec" aria-hidden="true"></span><span class="label">Play</span></button>'
        f"</div>{cap}</figure>"
    )


YT_LINE = re.compile(r"^\s*\[\[youtube:\s*([^\]\|]+?)\s*(?:\|\s*(.*?))?\s*\]\]\s*$", re.I)


class YouTubePreprocessor(Preprocessor):
    """A line containing only [[youtube:ID|Caption]] becomes a click-to-play embed."""

    def run(self, lines):
        out = []
        for line in lines:
            m = YT_LINE.match(line)
            if m:
                out += ["", self.md.htmlStash.store(youtube_html(youtube_id(m.group(1)), m.group(2) or "")), ""]
            else:
                out.append(line)
        return out


class FigureProcessor(Treeprocessor):
    """An image alone in its paragraph becomes <figure>, with its "title" as the caption."""

    def __init__(self, md, base_class: str | None):
        super().__init__(md)
        self.base_class = base_class

    def run(self, root):
        for p in root.iter("p"):
            kids = list(p)
            if len(kids) != 1 or kids[0].tag != "img" or (p.text or "").strip() or (kids[0].tail or "").strip():
                continue
            img = kids[0]
            p.tag, p.text = "figure", None
            img.tail = None
            classes = " ".join(c for c in (self.base_class, img.attrib.pop("class", "")) if c)
            if classes:
                p.set("class", classes)
            img.set("loading", "lazy")
            caption = img.attrib.pop("title", None)
            if caption:
                etree.SubElement(p, "figcaption").text = caption


class InsigniaExtension(Extension):
    def __init__(self, ctx: LinkContext, figure_class: str | None = None, **kwargs):
        self.ctx, self.figure_class = ctx, figure_class
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        md.preprocessors.register(YouTubePreprocessor(md), "youtube", 25)
        md.inlinePatterns.register(WikiLinkPattern(self.ctx, md), "wikilink", 175)
        md.treeprocessors.register(FigureProcessor(md, self.figure_class), "figures", 6)


FOOTNOTES_RE = re.compile(r'<div class="footnote">\s*<hr\s*/?>\s*(<ol>.*</ol>)\s*</div>\s*\Z', re.S)


def reader_breaks(html: str) -> str:
    """Chapters show every new line as a line break (CSS white-space: pre-line), so a
    Markdown hard break (two trailing spaces) must not also keep its newline."""
    return re.sub(r"<br\s*/?>\n", "<br>", html)


def split_footnotes(html: str):
    m = FOOTNOTES_RE.search(html)
    return (html[: m.start()], m.group(1)) if m else (html, "")


# ─── The builder ────────────────────────────────────────────────────────────

class Builder:
    def __init__(self, drafts: bool = False):
        self.drafts = drafts
        self.warnings: list[str] = []
        self.missing: dict[str, set] = {}

    def warn(self, message: str):
        self.warnings.append(message)

    # ── entry point
    def run(self):
        started = time.time()
        self.site = self.load_site()
        self.base = self.site["base_url"]
        self.load_wiki()
        self.load_novel()
        self.load_pages()
        self.load_media()
        self.render_markdown()
        self.cross_link()

        with build_lock():
            # a folder of our own, so a build in another process can't overwrite it
            self.out = ROOT / f".dist-tmp-{os.getpid()}"
            shutil.rmtree(self.out, ignore_errors=True)
            self.out.mkdir()
            try:
                if STATIC.exists():
                    shutil.copytree(STATIC, self.out, dirs_exist_ok=True)
                self.bundle_assets()
                self.render_site()
                self.write_search_index()
                replace_dist(self.out)
            finally:
                shutil.rmtree(self.out, ignore_errors=True)   # only still there if the build failed
        self.report(time.time() - started)

    # ── loading
    def load_site(self) -> dict:
        site = load_yaml(CONTENT / "site.yaml") or {}
        site.setdefault("title", "INSIGNIA")
        site.setdefault("tagline", "")
        site.setdefault("description", "")
        site.setdefault("language", "en")
        for key in ("nav", "footer_links"):
            site[key] = site.get(key) or []
        for key in ("home", "archive", "footer"):
            site[key] = site.get(key) or {}
        site["archive"].setdefault("name", "The Archive")
        # A host can set these without editing site.yaml (the GitHub Pages workflow does)
        for key, env in (("base_url", "INSIGNIA_BASE_URL"), ("site_url", "INSIGNIA_SITE_URL")):
            if env in os.environ:
                site[key] = os.environ[env]
        base = str(site.get("base_url") or "").strip().strip("/")
        site["base_url"] = f"/{base}" if base else ""
        return site

    def load_wiki(self):
        self.articles, self.index = [], {}
        for path in sorted((CONTENT / "wiki").glob("*.md")):
            if path.name.startswith("_"):
                continue
            meta, body = read_markdown(path)
            if meta.get("draft") and not self.drafts:
                continue
            slug = norm(meta.get("slug") or path.stem)
            title = str(meta.get("title") or path.stem.replace("-", " ").capitalize())
            self.articles.append({
                "kind": "wiki", "slug": slug, "title": title, "url": f"/wiki/{slug}/",
                "meta": meta, "body": body, "path": path,
            })
        for a in self.articles:
            for key in (a["slug"], a["title"], *as_list(a["meta"].get("aliases"))):
                k = norm(key)
                other = self.index.get(k)
                if other is not None and other is not a:
                    self.warn(f"'{key}' names both wiki/{other['path'].name} and wiki/{a['path'].name} — the first wins")
                    continue
                self.index[k] = a
        self.by_slug = {a["slug"]: a for a in self.articles}

    def lookup(self, title):
        k = norm(title)
        hit = self.index.get(k)
        if hit is None and k.endswith("es"):
            hit = self.index.get(k[:-2])
        if hit is None and k.endswith("s"):
            hit = self.index.get(k[:-1])
        return hit

    def load_novel(self):
        self.books, self.chapters = [], []
        root = CONTENT / "novel"
        if not root.exists():
            return
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = load_yaml(folder / "_book.yaml") or {}
            if meta.get("draft") and not self.drafts:
                continue
            slug = norm(meta.get("slug") or folder.name)
            book = {
                "kind": "book", "slug": slug, "meta": meta, "url": f"/novel/{slug}/",
                "title": str(meta.get("title") or folder.name), "subtitle": meta.get("subtitle", ""),
                "author": meta.get("author") or self.site.get("author", ""), "cover": meta.get("cover"),
                "status": meta.get("status", ""), "order": meta.get("order", 999), "path": folder,
            }
            chapters = []
            for path in sorted(folder.glob("*.md")):
                cmeta, body = read_markdown(path)
                if cmeta.get("draft") and not self.drafts:
                    continue
                m = re.match(r"^(\d+)[-_ .]+(.+)$", path.stem)
                cslug = norm(cmeta.get("slug") or (m.group(2) if m else path.stem))
                chapters.append({
                    "kind": "chapter", "book": book, "slug": cslug, "meta": cmeta, "body": body, "path": path,
                    "title": str(cmeta.get("title") or cslug.replace("-", " ").capitalize()),
                    "subtitle": cmeta.get("subtitle", ""), "date": to_date(cmeta.get("date")),
                    "url": f"{book['url']}{cslug}/",
                })
            for i, ch in enumerate(chapters):
                ch["number"] = str(ch["meta"].get("number") or f"{i + 1:02d}")
                ch["label"] = ch["meta"].get("label") or f"Chapter {ch['number']}"
                ch["prev"] = chapters[i - 1] if i else None
                ch["next"] = chapters[i + 1] if i + 1 < len(chapters) else None
            book["chapters"] = chapters
            self.books.append(book)
        self.books.sort(key=lambda b: (b["order"], b["title"]))
        self.chapters = [c for b in self.books for c in b["chapters"]]

    def load_pages(self):
        self.pages = []
        for path in sorted((CONTENT / "pages").glob("*.md")):
            meta, body = read_markdown(path)
            if meta.get("draft") and not self.drafts:
                continue
            slug = norm(meta.get("slug") or path.stem)
            if slug in RESERVED_SLUGS:
                raise BuildError(f"{rel(path)}: the address /{slug}/ is used by the site itself — pick another slug.")
            self.pages.append({
                "kind": "page", "slug": slug, "meta": meta, "body": body, "path": path, "url": f"/{slug}/",
                "title": str(meta.get("title") or slug.capitalize()), "subtitle": meta.get("subtitle", ""),
                "date": to_date(meta.get("date")),
            })

    def load_media(self):
        raw = load_yaml(CONTENT / "gallery.yaml") or []
        self.gallery = []
        for i, w in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(w, dict) or not w.get("image"):
                self.warn(f"content/gallery.yaml: item {i + 1} has no `image` — skipped")
                continue
            if w.get("draft") and not self.drafts:
                continue
            wid = str(w.get("id") or f"{i + 1:03d}")
            self.gallery.append({
                "kind": "work", "id": wid, "title": str(w.get("title") or f"Untitled {wid}"),
                "image": w["image"], "thumb": w.get("thumb") or w["image"], "alt": w.get("alt") or w.get("title", ""),
                "medium": w.get("medium", ""), "date": to_date(w.get("date")), "body": str(w.get("description") or ""),
                "tags": [{"name": str(t), "slug": norm(t)} for t in as_list(w.get("tags"))],
                "entries_raw": as_list(w.get("wiki")), "url": f"/gallery/#w-{wid}",
            })
        raw = load_yaml(CONTENT / "films.yaml") or []
        self.films = []
        for i, f in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(f, dict) or not f.get("youtube"):
                self.warn(f"content/films.yaml: item {i + 1} has no `youtube` id — skipped")
                continue
            if f.get("draft") and not self.drafts:
                continue
            vid = youtube_id(f["youtube"])
            duration = f.get("duration", "")
            if isinstance(duration, int):        # YAML reads an unquoted 7:44 as 464 seconds
                duration = f"{duration // 60}:{duration % 60:02d}"
            self.films.append({
                "kind": "film", "id": vid, "title": str(f.get("title") or "Untitled film"),
                "date": to_date(f.get("date")), "duration": str(duration), "body": str(f.get("description") or ""),
                "thumbnail": f.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                "custom_thumb": bool(f.get("thumbnail")), "entries_raw": as_list(f.get("wiki")), "url": f"/films/#f-{vid}",
            })

    # ── markdown
    def markdown(self, text: str, ctx: LinkContext, figure_class: str | None = None):
        md = ctx._md.get(figure_class)
        if md is None:
            md = markdown.Markdown(
                extensions=[
                    "abbr", "attr_list", "def_list", "fenced_code", "footnotes", "md_in_html", "tables",
                    "sane_lists", "smarty", TocExtension(slugify=slugify_unicode, toc_depth="2-4"),
                    InsigniaExtension(ctx, figure_class),
                ],
                extension_configs={"footnotes": {"BACKLINK_TEXT": "↑", "BACKLINK_TITLE": "Back to note %d in the text"}},
                output_format="html",
            )
            ctx._md[figure_class] = md
        md.reset()
        html = md.convert(text)
        return html, getattr(md, "toc_tokens", [])

    def inline(self, text, ctx: LinkContext) -> str:
        html, _ = self.markdown(str(unyaml_link(text)), ctx)
        m = re.fullmatch(r"<p>(.*)</p>", html.strip(), re.S)
        return m.group(1) if m else html.strip()

    def infobox(self, spec, ctx: LinkContext, default_title: str):
        if not isinstance(spec, dict):
            return None
        rows = []
        for row in as_list(spec.get("rows")):
            if isinstance(row, dict):
                for key, value in row.items():
                    if key == "header":
                        rows.append({"header": self.inline(value, ctx)})
                    else:
                        value = unyaml_link(value)
                        value = "<br>".join(self.inline(v, ctx) for v in as_list(value)) if isinstance(value, list) \
                            else self.inline(value, ctx)
                        rows.append({"label": self.inline(key, ctx), "value": value})
            elif isinstance(row, str):
                rows.append({"full": self.inline(row, ctx)})
        return {
            "title": spec.get("title") or default_title, "subtitle": spec.get("subtitle", ""),
            "image": spec.get("image"), "caption": self.inline(spec["caption"], ctx) if spec.get("caption") else "",
            "color": spec.get("color"), "rows": rows,
        }

    def navbox(self, spec, ctx: LinkContext):
        return {
            "title": self.inline(spec.get("title", ""), ctx),
            "groups": [
                {"label": self.inline(g.get("label", ""), ctx),
                 "items": [self.inline(i, ctx) for i in as_list(g.get("items"))]}
                for g in as_list(spec.get("groups")) if isinstance(g, dict)
            ],
        }

    def resolve_entries(self, names, ctx: LinkContext, where: str) -> list:
        for name in names:
            entry = self.lookup(name[0] if isinstance(name, list) else name)
            if entry is None:
                self.missing.setdefault(str(name).strip("[]"), set()).add(where)
            else:
                ctx.links[entry["slug"]] = None
        return [self.by_slug[s] for s in ctx.links]

    def render_markdown(self):
        navboxes = load_yaml(CONTENT / "navboxes.yaml") or {}
        for a in self.articles:
            meta, where = a["meta"], rel(a["path"])
            ctx = LinkContext(self, where, self_slug=a["slug"])
            html, toc = self.markdown(a["body"], ctx, figure_class="thumb")
            html, notes = split_footnotes(html)
            a.update(html=html, notes=notes, toc=toc)
            a["infobox"] = self.infobox(meta.get("infobox"), ctx, a["title"])
            a["hatnotes"] = [self.inline(h, ctx) for h in as_list(meta.get("hatnote"))]
            a["links_out"] = list(ctx.links)
            # navbox links don't count as backlinks
            nav_ctx = LinkContext(self, "content/navboxes.yaml", self_slug=a["slug"])
            a["navboxes"] = []
            for name in as_list(meta.get("navbox")):
                if name in navboxes:
                    a["navboxes"].append(self.navbox(navboxes[name], nav_ctx))
                else:
                    self.warn(f"{where}: navbox '{name}' is not defined in content/navboxes.yaml")
            a["categories"] = [{"name": str(c), "slug": norm(c), "url": f"/wiki/category/{norm(c)}/"}
                               for c in as_list(meta.get("categories"))]
            a["description"] = str(meta.get("description") or "")
            a["summary"] = (strip_tags(self.inline(meta["summary"], LinkContext(self, where)))
                            if meta.get("summary") else truncate(first_paragraph(html), 320))
            # the lead is shown on other pages, where its footnote markers would point nowhere
            a["lead"] = re.sub(r"<sup[^>]*>.*?</sup>", "", first_paragraph(html, as_html=True), flags=re.S)
            a["image"] = (a["infobox"] or {}).get("image") or first_image(html)
            a["date"] = to_date(meta.get("date"))
            a["updated"] = to_date(meta.get("updated")) or a["date"]
            a["sort"] = str(meta.get("sort") or a["title"])

        for ch in self.chapters:
            ctx = LinkContext(self, rel(ch["path"]))
            html, _ = self.markdown(ch["body"], ctx)
            html, notes = split_footnotes(reader_breaks(html))
            ch.update(html=html, notes=notes, minutes=reading_minutes(html), links_out=list(ctx.links))
            ch["entries"] = [self.by_slug[s] for s in ctx.links]
            ch["summary"] = str(ch["meta"].get("summary") or ch["subtitle"] or truncate(first_paragraph(html), 200))
            ch["image"] = ch["meta"].get("cover") or first_image(html)

        for book in self.books:
            ctx = LinkContext(self, rel(book["path"] / "_book.yaml"))
            book["synopsis"], _ = self.markdown(str(book["meta"].get("synopsis") or ""), ctx)
            book["minutes"] = sum(c["minutes"] for c in book["chapters"])
            dates = [c["date"] for c in book["chapters"] if c["date"]]
            book["updated"] = max(dates) if dates else None

        for page in self.pages:
            ctx = LinkContext(self, rel(page["path"]))
            html, _ = self.markdown(page["body"], ctx)
            html, notes = split_footnotes(reader_breaks(html))
            page.update(html=html, notes=notes, minutes=reading_minutes(html))
            page["summary"] = str(page["meta"].get("summary") or page["subtitle"] or truncate(first_paragraph(html), 200))

        for item in (*self.gallery, *self.films):
            where = f"content/{'gallery' if item['kind'] == 'work' else 'films'}.yaml ({item['title']})"
            ctx = LinkContext(self, where)
            item["html"], _ = self.markdown(item["body"], ctx)
            item["summary"] = truncate(strip_tags(item["html"]), 200)
            item["entries"] = self.resolve_entries(item["entries_raw"], ctx, where)

    def cross_link(self):
        for a in self.articles:
            a["backlinks"], a["appearances"] = [], []
        for a in self.articles:
            for slug in a["links_out"]:
                if slug != a["slug"]:
                    self.by_slug[slug]["backlinks"].append(a)
        for ch in self.chapters:
            for slug in ch["links_out"]:
                self.by_slug[slug]["appearances"].append({
                    "kind": "Novel", "title": ch["title"], "url": ch["url"],
                    "context": f"{ch['book']['title']}, {ch['label'].lower()}",
                })
        for w in self.gallery:
            for a in w["entries"]:
                a["appearances"].append({"kind": "Gallery", "title": w["title"], "url": w["url"],
                                         "context": w["medium"], "image": w["thumb"]})
        for f in self.films:
            for a in f["entries"]:
                a["appearances"].append({"kind": "Film", "title": f["title"], "url": f["url"],
                                         "context": f["duration"]})

        self.categories = {}
        for a in self.articles:
            for c in a["categories"]:
                cat = self.categories.setdefault(c["slug"], {**c, "pages": []})
                cat["pages"].append(a)
        for cat in self.categories.values():
            cat["pages"].sort(key=lambda p: p["sort"].casefold())

    # ── output
    def u(self, path):
        """Prefix the base path (for JSON; HTML attributes are rewritten automatically)."""
        if isinstance(path, str) and path.startswith("/") and not path.startswith("//"):
            return self.base + path
        return path or ""

    ATTR_URL = re.compile(r"""(\s(?:href|src|poster|action|data-src)=["'])/(?!/)""")
    CSS_URL = re.compile(r"""(url\(\s*["']?)/(?!/)""")

    def with_base(self, text: str) -> str:
        if not self.base:
            return text
        text = self.ATTR_URL.sub(lambda m: m.group(1) + self.base + "/", text)
        return self.CSS_URL.sub(lambda m: m.group(1) + self.base + "/", text)

    def write(self, url: str, text: str):
        path = self.out / url.strip("/")
        if url.endswith("/"):
            path = path / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.with_base(text), encoding="utf-8")

    def bundle_assets(self):
        css = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ASSETS / "css").glob("*.css")))
        js = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ASSETS / "js").glob("*.js")))
        self.asset_version = hashlib.sha1((css + js).encode()).hexdigest()[:10]
        (self.out / "assets").mkdir(exist_ok=True)
        (self.out / "assets" / "site.css").write_text(self.with_base(css), encoding="utf-8")
        (self.out / "assets" / "site.js").write_text(js, encoding="utf-8")

    def feed(self, limit=8):
        items = [{"date": c["date"], "kind": "Chapter", "title": c["title"], "sub": f"{c['book']['title']} · {c['label']}",
                  "url": c["url"]} for c in self.chapters]
        items += [{"date": a["date"], "kind": "Archive", "title": a["title"], "sub": a["description"], "url": a["url"]}
                  for a in self.articles]
        items += [{"date": w["date"], "kind": "Gallery", "title": w["title"], "sub": w["medium"], "url": w["url"]}
                  for w in self.gallery]
        items += [{"date": f["date"], "kind": "Film", "title": f["title"], "sub": f["duration"], "url": f["url"]}
                  for f in self.films]
        items += [{"date": p["date"], "kind": "Page", "title": p["title"], "sub": p["subtitle"], "url": p["url"]}
                  for p in self.pages]
        return sorted((i for i in items if i["date"]), key=lambda i: i["date"], reverse=True)[:limit]

    def letter_groups(self, pages):
        groups: dict[str, list] = {}
        for p in sorted(pages, key=lambda p: p["sort"].casefold()):
            groups.setdefault(index_letter(p["sort"]), []).append(p)
        return list(groups.items())

    def render_site(self):
        env = Environment(
            loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "xml"]),
            undefined=ChainableUndefined, trim_blocks=True, lstrip_blocks=True,
        )
        env.filters["date"] = format_date
        env.filters["pad"] = lambda n, width=2: str(n).zfill(width)
        stats = {"books": len(self.books), "chapters": len(self.chapters), "works": len(self.gallery),
                 "films": len(self.films), "entries": len(self.articles)}
        env.globals.update(site=self.site, asset_version=self.asset_version, stats=stats, today=date.today())

        def page(template, url, **ctx):
            try:
                self.write(url, env.get_template(template).render(url=url, **ctx))
            except TemplateError as e:
                where = f"{e.filename or template}" + (f", line {e.lineno}" if getattr(e, "lineno", None) else "")
                raise BuildError(f"templates/{where}: {e.message}") from None

        home = self.site["home"]
        counts = {"novel": len(self.chapters), "gallery": len(self.gallery), "films": len(self.films),
                  "wiki": len(self.articles)}
        tiles = [{**t, "url": t.get("url") or f"/{t.get('section')}/", "count": counts.get(t.get("section"), "")}
                 for t in as_list(home.get("tiles")) if isinstance(t, dict)]
        featured_book = next((b for b in self.books if b["slug"] == home.get("featured_book")),
                             self.books[0] if self.books else None)
        featured_entry = self.lookup(home.get("featured_entry") or "") if home.get("featured_entry") else None
        page("home.html", "/", mode="shell", section="home", tiles=tiles, feed=self.feed(),
             featured_book=featured_book, entry=featured_entry)

        # novel
        page("novel_index.html", "/novel/", mode="shell", section="novel", books=self.books,
             page_title="Novel")
        for book in self.books:
            page("book.html", book["url"], mode="shell", section="novel", book=book, page_title=book["title"],
                 page_description=truncate(strip_tags(book["synopsis"]), 200), page_image=book["cover"])
            for ch in book["chapters"]:
                page("chapter.html", ch["url"], mode="reader", section="novel", book=book, doc=ch,
                     page_title=f"{ch['title']} — {book['title']}", page_description=ch["summary"],
                     page_image=ch["image"], og_type="article")

        # standalone pages (About, …)
        for p in self.pages:
            page("page.html", p["url"], mode="reader", section=p["slug"], doc=p, page_title=p["title"],
                 page_description=p["summary"])

        # the Archive (wiki)
        archive = self.site["archive"]
        main_ctx = LinkContext(self, "content/site.yaml (archive.did_you_know)")
        dyk = [self.inline(d, main_ctx) for d in as_list(archive.get("did_you_know"))]
        featured = self.lookup(archive.get("featured") or "") if archive.get("featured") else None
        featured = featured or (self.articles[0] if self.articles else None)
        recent = sorted((a for a in self.articles if a["date"]), key=lambda a: a["date"], reverse=True)[:6]
        categories = sorted(self.categories.values(), key=lambda c: c["name"].casefold())
        page("wiki_main.html", "/wiki/", mode="wiki", section="wiki", featured=featured, dyk=dyk,
             recent=recent, categories=categories, page_title=archive["name"])
        page("wiki_list.html", "/wiki/all/", mode="wiki", section="wiki", list_title="All entries",
             groups=self.letter_groups(self.articles), total=len(self.articles), page_title="All entries")
        page("wiki_categories.html", "/wiki/categories/", mode="wiki", section="wiki",
             categories=categories, page_title="Categories")
        for cat in categories:
            page("wiki_list.html", cat["url"], mode="wiki", section="wiki", category=cat,
                 list_title=f"Category: {cat['name']}", groups=self.letter_groups(cat["pages"]),
                 total=len(cat["pages"]), page_title=f"Category: {cat['name']}")
        for a in self.articles:
            page("wiki_article.html", a["url"], mode="wiki", section="wiki", doc=a, page_title=a["title"],
                 page_description=a["description"] or a["summary"], page_image=a["image"], og_type="article")

        # gallery & films
        works_json = [{"id": w["id"], "title": w["title"], "image": self.u(w["image"]), "alt": w["alt"],
                       "medium": w["medium"], "date": format_date(w["date"], "dots"), "html": self.with_base(w["html"]),
                       "entries": [{"title": e["title"], "url": self.u(e["url"])} for e in w["entries"]]}
                      for w in self.gallery]
        tags: dict[str, dict] = {}
        for w in self.gallery:
            for t in w["tags"]:
                tags.setdefault(t["slug"], {**t, "count": 0})["count"] += 1
        page("gallery.html", "/gallery/", mode="shell", section="gallery", works=self.gallery,
             works_json=works_json, tags=list(tags.values()), page_title="Gallery")
        page("films.html", "/films/", mode="shell", section="films", films=self.films, page_title="Films")
        page("404.html", "/404.html", mode="shell", section="", page_title="Not found")

    def write_search_index(self):
        items = []
        for a in self.articles:
            items.append({"t": a["title"], "u": self.u(a["url"]), "k": "Archive", "d": a["description"],
                          "s": a["summary"], "i": self.u(a["image"]), "a": [str(x) for x in as_list(a["meta"].get("aliases"))]})
        for c in self.chapters:
            items.append({"t": c["title"], "u": self.u(c["url"]), "k": "Chapter",
                          "d": f"{c['book']['title']} · {c['label']}", "s": c["summary"], "i": self.u(c["image"])})
        for w in self.gallery:
            items.append({"t": w["title"], "u": self.u(w["url"]), "k": "Gallery", "d": w["medium"],
                          "s": w["summary"], "i": self.u(w["thumb"])})
        for f in self.films:
            items.append({"t": f["title"], "u": self.u(f["url"]), "k": "Film", "d": f["duration"],
                          "s": f["summary"], "i": self.u(f["thumbnail"])})
        for p in self.pages:
            items.append({"t": p["title"], "u": self.u(p["url"]), "k": "Page", "d": p["subtitle"], "s": p["summary"]})
        (self.out / "search.json").write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")),
                                               encoding="utf-8")

    def report(self, seconds: float):
        print(f"✓ Built {len(self.articles)} archive entries, {len(self.chapters)} chapters, "
              f"{len(self.gallery)} works, {len(self.films)} films, {len(self.pages)} pages "
              f"in {seconds:.2f}s → {rel(DIST)}/")
        for w in self.warnings:
            print(f"  ! {w}")
        if self.missing:
            print("  · Links to entries not written yet (shown as red links):")
            for title, places in sorted(self.missing.items()):
                print(f"      {title}  ← {', '.join(sorted(places))}")


# ─── Dev server ─────────────────────────────────────────────────────────────

class DevHandler(http.server.SimpleHTTPRequestHandler):
    base = ""

    def translate_path(self, path):
        if self.base and path.startswith(self.base):
            path = path[len(self.base):] or "/"
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        page = DIST / "404.html"
        if code == 404 and page.exists():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def log_message(self, *args):
        pass


def safe_build(drafts: bool) -> Builder | None:
    try:
        builder = Builder(drafts)
        builder.run()
        return builder
    except BuildError as e:
        print(f"\n✗ {e}\n", file=sys.stderr)
    except Exception:
        traceback.print_exc()
    return None


def snapshot():
    return {p: p.stat().st_mtime for d in (CONTENT, TEMPLATES, ASSETS, STATIC) if d.exists()
            for p in d.rglob("*") if p.is_file()}


def watch(drafts: bool):
    last = snapshot()
    while True:
        time.sleep(0.7)
        current = snapshot()
        if current != last:
            last = current
            print(time.strftime("[%H:%M:%S] change detected — rebuilding"))
            safe_build(drafts)


def serve(port: int, drafts: bool):
    builder = safe_build(drafts)
    DevHandler.base = builder.base if builder else ""
    DIST.mkdir(exist_ok=True)
    handler = partial(DevHandler, directory=str(DIST))
    for candidate in range(port, port + 20):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            break
        except OSError:
            continue
    else:
        sys.exit(f"No free port between {port} and {port + 19}.")
    threading.Thread(target=watch, args=(drafts,), daemon=True).start()
    print(f"\n  Serving on  http://localhost:{candidate}{DevHandler.base}/\n  Edit anything in content/, templates/ "
          f"or assets/ and refresh. Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    parser = argparse.ArgumentParser(description="Build the Insignia site.")
    parser.add_argument("command", nargs="?", choices=["build", "serve"], default="build")
    parser.add_argument("--drafts", action="store_true", help="include content marked `draft: true`")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.port, args.drafts)
    elif safe_build(args.drafts) is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
