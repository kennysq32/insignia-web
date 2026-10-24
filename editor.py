"""Manuscript editor: private authenticated gateway in production, loopback in development."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import os
import re
import tempfile
from datetime import datetime
from urllib.parse import parse_qs

import yaml


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class EditorAPI:
    def __init__(self, site, drafts=False):
        self.site = site
        self.drafts = drafts

    @staticmethod
    def check_request(headers, port, method):
        host = headers.get("Host", "")
        token_file = os.environ.get("INSIGNIA_PROXY_TOKEN_FILE")
        if token_file:
            expected = Path(token_file).read_text().strip()
            actual = headers.get("X-Insignia-Proxy-Token", "")
            if len(expected) < 43 or not hmac.compare_digest(actual, expected):
                raise APIError(403, "인증된 편집 서버에서 접속해 주세요.")
        elif host not in {f"localhost:{port}", f"127.0.0.1:{port}"}:
            raise APIError(403, "로컬 주소에서 편집기를 열어 주세요.")
        origin = headers.get("Origin")
        if origin and origin != f"http://{host}":
            raise APIError(403, "현재 페이지에서 시작한 요청만 허용됩니다.")
        if method == "POST":
            if headers.get("X-Insignia-Editor") != "1":
                raise APIError(403, "편집기에서 다시 시도해 주세요.")
            if headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise APIError(415, "JSON 요청만 허용됩니다.")

    def handle(self, method, path, query, payload):
        with self.site.SITE_LOCK:
            if method == "GET" and path == "/__editor/api/library":
                return {"books": self.library()}
            if method == "GET" and path == "/__editor/api/document":
                params = parse_qs(query)
                return self.document(params.get("book", [""])[0], params.get("chapter", [None])[0])
            if method == "POST" and path == "/__editor/api/save":
                return self.save(payload)
            if method == "POST" and path == "/__editor/api/preview":
                return self.preview(payload)
        raise APIError(404, "요청한 편집 기능을 찾을 수 없습니다.")

    def catalog(self):
        builder = self.site.Builder(drafts=True)
        builder.site = builder.load_site()
        builder.base = builder.site["base_url"]
        builder.load_novel()
        return builder

    def library(self):
        builder = self.catalog()
        return [{
            "id": b["path"].name, "title": b["title"], "subtitle": str(b["subtitle"] or ""),
            "read_url": None if b["meta"].get("draft") else builder.u(b["url"]),
            "chapters": [{"id": c["path"].name, "title": c["title"],
                          "draft": bool(c["meta"].get("draft")), "number": c["number"]}
                         for c in b["chapters"]],
        } for b in builder.books]

    def folder(self, book):
        if not isinstance(book, str) or not book or book in {".", ".."} or re.search(r"[\\/:]", book):
            raise APIError(400, "책을 선택해 주세요.")
        root = (self.site.CONTENT / "novel").resolve()
        folder = (root / book).resolve()
        if folder.parent != root or not folder.is_dir():
            raise APIError(404, "책을 찾을 수 없습니다.")
        return folder

    def path(self, book, chapter):
        folder = self.folder(book)
        if chapter is None:
            name = "_book.yaml"
        elif (not isinstance(chapter, str) or not chapter.endswith(".md")
              or chapter.startswith((".", "_")) or re.search(r"[\\/:]", chapter)):
            raise APIError(400, "챕터 파일 이름이 올바르지 않습니다.")
        else:
            name = chapter
        path = (folder / name).resolve()
        if path.parent != folder:
            raise APIError(400, "원고 폴더 안의 파일만 편집할 수 있습니다.")
        return path

    @staticmethod
    def revision(raw):
        return hashlib.sha256(raw).hexdigest()

    def document(self, book, chapter=None):
        path = self.path(book, chapter)
        if chapter is not None and not path.is_file():
            raise APIError(404, "챕터를 찾을 수 없습니다.")
        raw = path.read_bytes() if path.exists() else b""
        builder = self.catalog()
        record = next((b for b in builder.books if b["path"].name == book), None)
        if record is None:
            raise APIError(404, "책을 찾을 수 없습니다.")
        if chapter is None:
            meta = record["meta"]
            fields = {key: str(meta.get(key) or "") for key in
                      ("title", "subtitle", "author", "cover", "status", "synopsis")}
            fields["title"] = record["title"]
            fields["genres"] = ", ".join(record["genres"])
            url = None if meta.get("draft") else builder.u(record["url"])
        else:
            ch = next((c for c in record["chapters"] if c["path"].name == chapter), None)
            if ch is None:
                raise APIError(404, "챕터를 찾을 수 없습니다.")
            fields = {"title": ch["title"], "alternate_title": str(ch["meta"].get("title") or ""),
                      "subtitle": str(ch["subtitle"] or ""), "date": ch["date"].isoformat() if ch["date"] else "",
                      "draft": bool(ch["meta"].get("draft")), "body": ch["body"]}
            url = None if fields["draft"] or record["meta"].get("draft") else builder.u(ch["url"])
        return {"book": book, "chapter": chapter, "kind": "chapter" if chapter else "book",
                "fields": fields, "revision": self.revision(raw), "read_url": url}

    @staticmethod
    def text(fields, key, limit=1000, required=False):
        value = fields.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            raise APIError(400, f"{key} 항목의 길이나 형식을 확인해 주세요.")
        if required and not value.strip():
            raise APIError(400, "제목을 입력해 주세요.")
        return value if key in {"body", "synopsis"} else value.strip()

    @staticmethod
    def atomic_write(path, raw):
        fd, name = tempfile.mkstemp(prefix=".editor-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def save(self, payload):
        book, chapter = payload.get("book"), payload.get("chapter")
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise APIError(400, "저장할 원고를 확인해 주세요.")
        title = self.text(fields, "title", required=True)
        creating = payload.get("new") is True
        if creating:
            folder = self.folder(book)
            if chapter is not None:
                raise APIError(400, "새 챕터 요청이 올바르지 않습니다.")
            number = max((int(m.group(1)) for p in folder.glob("*.md")
                          if (m := re.match(r"^(\d+)[-_ .]", p.name))), default=0) + 1
            slug = self.site.norm(title)[:80] or "chapter"
            used = {c["slug"] for b in self.catalog().books if b["path"].name == book for c in b["chapters"]}
            suffix, stem = 2, slug
            while slug in used:
                slug, suffix = f"{stem}-{suffix}", suffix + 1
            chapter = f"{number:02d}-{slug}.md"
            path = self.path(book, chapter)
            if path.exists():
                raise APIError(409, "같은 이름의 챕터가 있습니다. 제목을 바꿔 주세요.")
            previous, meta = None, {"slug": slug}
        else:
            path = self.path(book, chapter)
            if chapter is not None and not path.is_file():
                raise APIError(404, "챕터를 찾을 수 없습니다.")
            previous = path.read_bytes() if path.exists() else None
            if payload.get("revision") != self.revision(previous or b""):
                raise APIError(409, "다른 곳에서 원고가 수정되었습니다. 현재 원고를 복사한 뒤 새로고침해 주세요.")
            meta = (self.site.read_markdown(path)[0] if chapter else self.site.load_yaml(path)) or {}
        if chapter:
            meta["heading"] = title
            for field, key in (("alternate_title", "title"), ("subtitle", "subtitle"), ("date", "date")):
                value = self.text(fields, field)
                if key == "date" and value:
                    try:
                        datetime.strptime(value, "%Y-%m-%d")
                    except ValueError:
                        raise APIError(400, "날짜는 YYYY-MM-DD 형식으로 입력해 주세요.") from None
                if value:
                    meta[key] = value
                else:
                    meta.pop(key, None)
            if not isinstance(fields.get("draft"), bool):
                raise APIError(400, "공개 상태를 확인해 주세요.")
            if fields["draft"]:
                meta["draft"] = True
            else:
                meta.pop("draft", None)
            body = self.text(fields, "body", limit=1_500_000)
            text = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
        else:
            meta["title"] = title
            for key in ("subtitle", "author", "cover", "status", "synopsis"):
                meta[key] = self.text(fields, key, limit=100_000 if key == "synopsis" else 1000)
            meta["genres"] = [g.strip() for g in self.text(fields, "genres").split(",") if g.strip()]
            text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        if previous is not None:
            backup = self.site.ROOT / ".cache" / "editor" / book
            backup.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (backup / f"{stamp}-{path.name}").write_bytes(previous)
        self.atomic_write(path, text.encode("utf-8"))
        try:
            self.site.Builder(self.drafts, editing=True).run()
        except Exception:
            if previous is None:
                path.unlink()
            else:
                self.atomic_write(path, previous)
            raise APIError(500, "페이지를 갱신하지 못해 저장을 취소했습니다. 이전 원고는 유지됩니다.") from None
        return {"document": self.document(book, chapter), "books": self.library()}

    def preview(self, payload):
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise APIError(400, "미리 볼 원고를 확인해 주세요.")
        key = "synopsis" if payload.get("kind") == "book" else "body"
        body = self.text(fields, key, limit=1_500_000)
        builder = self.site.Builder(self.drafts)
        builder.site = builder.load_site()
        builder.base = builder.site["base_url"]
        builder.load_wiki()
        html, _ = builder.markdown(body, self.site.LinkContext(builder, "editor preview"))
        if key == "body":
            html = self.site.reader_breaks(html)
        html, notes = self.site.split_footnotes(html)
        return {"html": builder.with_base(html), "notes": builder.with_base(notes),
                "minutes": self.site.reading_minutes(html)}
