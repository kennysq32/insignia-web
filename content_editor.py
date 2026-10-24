"""Authenticated content management; all writes rebuild atomically."""
import base64
import binascii
from datetime import datetime
from io import BytesIO
import json
import mimetypes
from pathlib import Path
import re
import uuid
from urllib.parse import parse_qs
import yaml
from editor import APIError, EditorAPI

SECTIONS = {"novel": "Novel", "gallery": "Gallery", "films": "Films", "wiki": "Archive", "insignia-wiki": "위키", "about": "About"}
KINDS = {"gallery", "films", "archive", "pages", "books"}

class ContentEditor:
    def __init__(self, site):
        self.site = site

    def file(self, kind, item=None):
        root = self.site.CONTENT.resolve()
        if kind in {"gallery", "films"}:
            path = root / f"{kind}.yaml"
        elif kind == "settings":
            path = root / "publication.json"
        elif kind == "chapters":
            if not isinstance(item, str) or item.count("/") != 1: raise APIError(400, "챕터 주소를 확인해 주세요.")
            book, chapter = item.split("/")
            if not chapter.endswith(".md") or chapter.startswith((".", "_")) or re.search(r"[\\/:]", chapter): raise APIError(400, "챕터 주소를 확인해 주세요.")
            path = self.file("books", book).parent / chapter
        elif kind in {"archive", "pages", "books"}:
            if not isinstance(item, str) or not item or item.startswith((".", "_")) or re.search(r"[\\/:]", item):
                raise APIError(400, "항목 주소를 확인해 주세요.")
            path = root / ({"archive": "wiki", "pages": "pages", "books": "novel"}[kind]) / item
            if kind == "books":
                path /= "_book.yaml"
            elif not item.endswith(".md"):
                raise APIError(400, "문서 파일을 선택해 주세요.")
        else:
            raise APIError(400, "편집할 종류를 선택해 주세요.")
        # Resolve existing symlinks as well as the final name, for both reads and writes.
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
            raise APIError(400, "콘텐츠 폴더 안의 파일만 사용할 수 있습니다.")
        return path

    def raw(self, path):
        return path.read_bytes() if path.exists() else b""

    def items(self, kind):
        if kind in {"gallery", "films"}:
            value = self.site.load_yaml(self.file(kind)) or []
            if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
                raise APIError(400, "콘텐츠 목록 형식을 확인해 주세요.")
            return value
        return []

    def catalog(self):
        result = {kind: [] for kind in KINDS}
        trash = []
        def append(kind, item, meta, path, fallback):
            value = {"id": item, "title": str(meta.get("title") or fallback), "draft": bool(meta.get("draft"))}
            if meta.get("deleted"):
                trash.append({**value, "kind": kind, "revision": EditorAPI.revision(self.raw(path))})
            elif kind in result: result[kind].append(value)
        for kind in ("gallery", "films"):
            for i, meta in enumerate(self.items(kind)):
                append(kind, str(i), meta, self.file(kind), "제목 없음")
        for kind, folder in (("archive", "wiki"), ("pages", "pages")):
            for path in sorted((self.site.CONTENT / folder).glob("*.md")):
                if path.name.startswith(("_", ".")): continue
                self.file(kind, path.name)
                meta, _ = self.site.read_markdown(path)
                append(kind, path.name, meta, path, path.stem)
        for path in sorted((self.site.CONTENT / "novel").glob("*/_book.yaml")):
            self.file("books", path.parent.name)
            meta = self.site.load_yaml(path) or {}
            append("books", path.parent.name, meta, path, path.parent.name)
            if not meta.get("deleted"):
                for chapter in sorted(path.parent.glob("*.md")):
                    if chapter.name.startswith((".", "_")): continue
                    self.file("chapters", path.parent.name + "/" + chapter.name)
                    cmeta, _ = self.site.read_markdown(chapter)
                    append("chapters", path.parent.name + "/" + chapter.name, {**cmeta, "title": cmeta.get("heading") or cmeta.get("title") or chapter.stem}, chapter, chapter.stem)
        return {"items": result, "trash": trash, "settings": self.settings(), "revisions": {kind: EditorAPI.revision(self.raw(self.file(kind))) for kind in ("gallery", "films")}}

    def settings(self):
        path = self.file("settings")
        raw = self.raw(path)
        value = yaml.safe_load(raw) or {}
        return {"revision": EditorAPI.revision(raw), "sections": {key: value.get("sections", {}).get(key, True) for key in SECTIONS},
                "labels": {key: str(value.get("labels", {}).get(key) or label) for key, label in SECTIONS.items()}}

    def document(self, kind, item):
        if kind not in KINDS: raise APIError(400, "편집할 종류를 선택해 주세요.")
        path = self.file(kind, item)
        if kind in {"gallery", "films"}:
            rows = self.items(kind)
            if not isinstance(item, str) or not re.fullmatch(r"\d+", item) or int(item) >= len(rows): raise APIError(404, "항목을 찾을 수 없습니다.")
            meta, body = rows[int(item)], ""
        else:
            if not path.is_file(): raise APIError(404, "항목을 찾을 수 없습니다.")
            meta, body = (self.site.load_yaml(path) or {}, "") if kind == "books" else self.site.read_markdown(path)
        if meta.get("deleted"): raise APIError(404, "휴지통에 있는 항목입니다.")
        keys = {"gallery": ["title", "image", "thumb", "alt", "medium", "date", "description"],
                "films": ["title", "youtube", "thumbnail", "duration", "date", "description"],
                "archive": ["title", "description", "date"], "pages": ["title", "subtitle", "date"],
                "books": ["title", "subtitle", "author", "cover", "status", "synopsis"]}[kind]
        fields = {key: str(meta.get(key) or "") for key in keys}
        fields["draft"] = bool(meta.get("draft"))
        if kind in {"archive", "pages"}: fields["body"] = body
        for key in ({"gallery": ["tags", "wiki"], "films": ["wiki"], "archive": ["categories", "aliases"], "books": ["genres"]}.get(kind, [])):
            fields[key] = ", ".join(str(v) for v in self.site.as_list(meta.get(key)))
        return {"kind": kind, "id": item, "fields": fields, "revision": EditorAPI.revision(self.raw(path))}

    @staticmethod
    def date(value):
        if value:
            try: datetime.strptime(value, "%Y-%m-%d")
            except ValueError: raise APIError(400, "날짜는 YYYY-MM-DD 형식으로 입력해 주세요.") from None
        return value

    @staticmethod
    def asset(value, required=False):
        if not value and not required: return value
        if not isinstance(value, str) or len(value) > 2000 or re.search(r"[\x00-\x20<>\"'\\]", value): raise APIError(400, "이미지 주소를 확인해 주세요.")
        if re.match(r"^/(?:images|uploads)/[^?#]+$", value) and not any(p in {".", ".."} for p in value.split("/")): return value
        if re.match(r"^https://[^/]+/", value): return value
        raise APIError(400, "이미지는 업로드하거나 /images/ 주소 또는 HTTPS 주소를 입력해 주세요.")

    def commit(self, path, previous, text, kind):
        created_parent = not path.parent.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        if previous is not None:
            backup = self.site.ROOT / ".cache/editor/content" / kind
            backup.mkdir(parents=True, exist_ok=True)
            (backup / (datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + path.name)).write_bytes(previous)
        EditorAPI.atomic_write(path, text.encode())
        try: self.site.Builder(editing=True).run()
        except Exception:
            if previous is None:
                path.unlink(missing_ok=True)
                if created_parent and not any(path.parent.iterdir()): path.parent.rmdir()
            else: EditorAPI.atomic_write(path, previous)
            raise APIError(500, "페이지를 갱신하지 못해 저장을 취소했습니다. 기존 내용은 유지됩니다.") from None

    def save(self, payload):
        kind, item, fields = payload.get("kind"), payload.get("id"), payload.get("fields")
        if kind not in KINDS or not isinstance(fields, dict): raise APIError(400, "저장할 항목을 확인해 주세요.")
        creating = payload.get("new") is True
        if not isinstance(fields.get("draft"), bool): raise APIError(400, "공개 여부를 선택해 주세요.")
        title = EditorAPI.text(fields, "title", required=True)
        if creating and kind not in {"gallery", "films"}:
            stem = self.site.norm(title)[:70] or "item"
            item = stem if kind == "books" else stem + ".md"
            suffix = 2
            while self.file(kind, item).exists():
                item = f"{stem}-{suffix}" + ("" if kind == "books" else ".md"); suffix += 1
            if kind == "pages" and self.site.norm(item[:-3]) in self.site.RESERVED_SLUGS:
                raise APIError(400, "이 제목의 주소는 사이트에서 사용 중입니다. 다른 제목을 입력해 주세요.")
        path = self.file(kind, item)
        previous = self.raw(path) if path.exists() else None
        rows = self.items(kind) if kind in {"gallery", "films"} else None
        if not creating:
            if previous is None or payload.get("revision") != EditorAPI.revision(previous): raise APIError(409, "다른 곳에서 수정되었습니다. 새로고침 후 다시 편집해 주세요.")
            self.document(kind, item)  # Validate selected media index before writing.
        elif rows is not None and payload.get("revision") != EditorAPI.revision(previous or b""):
            raise APIError(409, "목록이 변경되었습니다. 새로고침 후 다시 추가해 주세요.")
        if rows is not None:
            meta = {} if creating else dict(rows[int(item)])
        else:
            meta = {} if creating else ((self.site.load_yaml(path) or {}) if kind == "books" else self.site.read_markdown(path)[0])
        meta["title"] = title
        meta["draft"] = fields["draft"]
        allowed = {"gallery": ["image", "thumb", "alt", "medium", "date", "description"],
                   "films": ["youtube", "thumbnail", "duration", "date", "description"],
                   "archive": ["description", "date"], "pages": ["subtitle", "date"],
                   "books": ["subtitle", "author", "cover", "status", "synopsis"]}[kind]
        for key in allowed:
            value = EditorAPI.text(fields, key, limit=100_000 if key in {"description", "synopsis"} else 2000)
            if key in {"image", "thumb", "thumbnail", "cover"}: self.asset(value, required=key == "image")
            if key == "date": self.date(value)
            if key == "youtube":
                try:
                    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", self.site.youtube_id(value)): raise ValueError()
                except Exception: raise APIError(400, "올바른 YouTube 주소 또는 영상 ID를 입력해 주세요.") from None
            meta[key] = value
        for key in {"gallery": ["tags", "wiki"], "films": ["wiki"], "archive": ["categories", "aliases"], "books": ["genres"]}.get(kind, []):
            meta[key] = [v.strip() for v in EditorAPI.text(fields, key, 5000).split(",") if v.strip()]
        if rows is not None:
            if creating:
                if kind == "gallery": meta["id"] = uuid.uuid4().hex[:12]
                item = str(len(rows)); rows.append(meta)
            else: rows[int(item)] = meta
            text = yaml.safe_dump(rows, allow_unicode=True, sort_keys=False)
        elif kind == "books": text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        else: text = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + EditorAPI.text(fields, "body", 1_500_000)
        self.commit(path, previous, text, kind)
        return {"document": self.document(kind, item), **self.catalog()}

    def trash(self, payload):
        kind, item, action = payload.get("kind"), payload.get("id"), payload.get("action")
        if kind not in KINDS | {"chapters"} or action not in {"trash", "restore"}: raise APIError(400, "휴지통 요청을 확인해 주세요.")
        path = self.file(kind, item)
        if not path.is_file(): raise APIError(404, "항목을 찾을 수 없습니다.")
        previous = path.read_bytes()
        if payload.get("revision") != EditorAPI.revision(previous): raise APIError(409, "다른 곳에서 수정되었습니다. 새로고침해 주세요.")
        rows = self.items(kind) if kind in {"gallery", "films"} else None
        if rows is not None:
            if not isinstance(item, str) or not re.fullmatch(r"\d+", item) or int(item) >= len(rows): raise APIError(404, "항목을 찾을 수 없습니다.")
            meta, body = dict(rows[int(item)]), ""
        elif kind == "books": meta, body = self.site.load_yaml(path) or {}, ""
        else: meta, body = self.site.read_markdown(path)
        if bool(meta.get("deleted")) != (action == "restore"): raise APIError(409, "항목의 휴지통 상태가 변경되었습니다. 새로고침해 주세요.")
        if action == "trash":
            meta["deleted"] = True; meta["deleted_at"] = datetime.now().isoformat()
        else:
            meta.pop("deleted", None); meta.pop("deleted_at", None); meta["draft"] = True
        if rows is not None:
            rows[int(item)] = meta; text = yaml.safe_dump(rows, allow_unicode=True, sort_keys=False)
        elif kind == "books": text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        else: text = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
        self.commit(path, previous, text, kind)
        return self.catalog()

    def save_settings(self, payload):
        current = self.settings()
        if payload.get("revision") != current["revision"]: raise APIError(409, "공개 설정이 변경되었습니다. 새로고침해 주세요.")
        sections, labels = payload.get("sections"), payload.get("labels")
        if not isinstance(sections, dict) or set(sections) != set(SECTIONS) or any(type(v) is not bool for v in sections.values()): raise APIError(400, "메뉴 공개 여부를 확인해 주세요.")
        if not isinstance(labels, dict) or set(labels) != set(SECTIONS): raise APIError(400, "메뉴 이름을 확인해 주세요.")
        labels = {key: EditorAPI.text(labels, key, 40, required=True) for key in SECTIONS}
        path = self.file("settings"); previous = self.raw(path) if path.exists() else None
        self.commit(path, previous, json.dumps({"sections": sections, "labels": labels}, ensure_ascii=False, indent=2) + "\n", "settings")
        return self.catalog()

    def media_file(self, value):
        if not isinstance(value, str) or not re.match(r"^/(images|uploads)/", value): raise APIError(404, "이미지를 찾을 수 없습니다.")
        root = self.site.STATIC.resolve(); path = (root / value.lstrip("/")).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise APIError(404, "이미지를 찾을 수 없습니다.")
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}: raise APIError(404, "이미지를 찾을 수 없습니다.")
        return path, mime

    def upload(self, payload):
        value = payload.get("data")
        if not isinstance(value, str) or len(value) > 28_000_000: raise APIError(413, "이미지는 20MB 이하로 선택해 주세요.")
        try: raw = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error): raise APIError(400, "이미지 파일을 읽을 수 없습니다.") from None
        if not raw or len(raw) > 20 * 1024 * 1024: raise APIError(413, "이미지는 20MB 이하로 선택해 주세요.")
        from PIL import Image
        try:
            with Image.open(BytesIO(raw)) as image:
                ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}.get(image.format)
                if not ext or image.width * image.height > 40_000_000: raise ValueError()
                image.verify()
        except Exception: raise APIError(415, "PNG, JPG, WebP, GIF 이미지 파일을 선택해 주세요.") from None
        folder = self.site.STATIC / "uploads"
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.site.STATIC.resolve()): raise APIError(400, "이미지 저장 폴더를 확인해 주세요.")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (uuid.uuid4().hex + "." + ext)
        EditorAPI.atomic_write(path, raw)
        return {"url": "/uploads/" + path.name}

    def preview(self, payload):
        fields = payload.get("fields")
        if not isinstance(fields, dict): raise APIError(400, "미리 볼 내용을 확인해 주세요.")
        body = next((fields[k] for k in ("body", "description", "synopsis") if k in fields), "")
        if not isinstance(body, str) or len(body) > 1_500_000: raise APIError(400, "미리 볼 내용을 확인해 주세요.")
        builder = self.site.Builder(drafts=True)
        builder.site = builder.load_site(); builder.base = builder.site["base_url"]; builder.load_wiki()
        html, _ = builder.markdown(body, self.site.LinkContext(builder, "content preview"))
        return {"html": html}

    def handle(self, method, endpoint, query, payload):
        params = parse_qs(query)
        if method == "GET" and endpoint == "catalog": return self.catalog()
        if method == "GET" and endpoint == "document": return self.document(params.get("kind", [""])[0], params.get("id", [""])[0])
        if method == "POST" and endpoint == "save": return self.save(payload)
        if method == "POST" and endpoint == "trash": return self.trash(payload)
        if method == "POST" and endpoint == "settings": return self.save_settings(payload)
        if method == "POST" and endpoint == "upload": return self.upload(payload)
        if method == "POST" and endpoint == "preview": return self.preview(payload)
        raise APIError(404, "요청한 편집 도구를 찾을 수 없습니다.")
