"""Git-tracked chronology data, served only through the authenticated editor."""

from __future__ import annotations

import calendar
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sqlite3
from urllib.parse import urlsplit

from editor import APIError, EditorAPI


class TimelineAPI:
    COLORS = {"red", "blue", "green", "gray"}

    def __init__(self, site):
        self.site = site

    @contextmanager
    def locked(self):
        """Serialize JSON reads/migrations/writes across server threads and processes."""
        folder = self.site.ROOT / ".private"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.site.SITE_LOCK, (folder / "timeline.lock").open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @property
    def source(self):
        path = self.site.ROOT / "timeline-data" / "timeline.json"
        if path.parent.is_symlink() or path.is_symlink():
            raise APIError(500, "타임라인 데이터는 저장소 안의 실제 JSON 파일이어야 합니다.")
        return path

    @property
    def migrated(self):
        return self.site.ROOT / ".private" / "timeline-json-migrated"

    def stored_value(self, value):
        if not isinstance(value, dict):
            raise APIError(500, "타임라인 JSON의 형식을 확인해 주세요.")
        try:
            return self.validate({**value, "version": 0})
        except APIError as error:
            raise APIError(500, f"타임라인 JSON을 확인해 주세요: {error}") from None

    def record(self, value, raw):
        # A content revision also detects Git checkouts and hand edits. It does
        # not depend on a local database counter, file timestamps, or a branch.
        return {**value, "version": hashlib.sha256(raw).hexdigest(),
                "updated_at": datetime.fromtimestamp(self.source.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}

    def write_source(self, value):
        raw = (json.dumps({"schema_version": 1, **value}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.source.parent.mkdir(parents=True, exist_ok=True)
        EditorAPI.atomic_write(self.source, raw)
        if not self.migrated.exists():
            self.migrated.touch()
        return self.record(value, raw)

    def migrate_legacy(self):
        """Copy the former SQLite store once; leave the original as a backup."""
        legacy = self.site.ROOT / ".private" / "timeline.sqlite3"
        if not legacy.is_file():
            return
        try:
            db = sqlite3.connect(legacy.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                row = db.execute("SELECT data FROM timeline WHERE id = 1").fetchone()
            finally:
                db.close()
            if row:
                self.write_source(self.stored_value(json.loads(row[0])))
        except (sqlite3.Error, ValueError, UnicodeDecodeError):
            raise APIError(500, "기존 SQLite 타임라인을 읽을 수 없습니다. 원본 파일을 확인해 주세요.") from None

    def read_document(self):
        if not self.source.exists():
            if self.migrated.exists():
                raise APIError(500, "타임라인 JSON이 없어졌습니다. Git이나 백업에서 복원해 주세요. 이전 SQLite 데이터로 덮어쓰지 않습니다.")
            self.migrate_legacy()
        if not self.source.exists():
            return {"version": 0, "title": "세계관 타임라인", "events": [], "updated_at": None}
        raw = self.source.read_bytes()
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise APIError(500, "타임라인 JSON을 읽을 수 없습니다. 파일 형식이나 Git 충돌 표시를 확인해 주세요.") from None
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise APIError(500, "지원하는 타임라인 JSON 형식(schema_version: 1)을 사용해 주세요.")
        value = self.stored_value(value)
        if not self.migrated.exists():
            self.migrated.touch()
        return self.record(value, raw)

    @staticmethod
    def sort_events(events):
        return sorted(events, key=lambda e: (e["year"], e["month"] or 0, e["day"] or 0, e["id"]))

    def document(self):
        with self.locked():
            return self.read_document()

    @staticmethod
    def text(data, key, limit, required=False):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise APIError(400, "제목과 설명의 길이·형식을 확인해 주세요.")
        return value.strip()

    def validate(self, payload):
        version = payload.get("version")
        if not ((type(version) is int and version >= 0)
                or (isinstance(version, str) and re.fullmatch(r"[0-9a-f]{64}", version))):
            raise APIError(400, "타임라인 버전을 확인해 주세요.")
        title = self.text(payload, "title", 120, required=True)
        rows = payload.get("events")
        if not isinstance(rows, list) or len(rows) > 2000:
            raise APIError(400, "사건은 2,000개까지 기록할 수 있습니다.")
        events, ids = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise APIError(400, "사건 형식을 확인해 주세요.")
            identifier = row.get("id")
            if (not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identifier)
                    or identifier in ids):
                raise APIError(400, "사건 ID가 올바르지 않거나 중복되었습니다.")
            ids.add(identifier)
            year, month, day = row.get("year"), row.get("month"), row.get("day")
            if type(year) is not int or not -999999 <= year <= 999999:
                raise APIError(400, "연도는 -999999부터 999999 사이의 정수로 입력해 주세요.")
            if month is not None and (type(month) is not int or not 1 <= month <= 12):
                raise APIError(400, "월은 1부터 12 사이로 입력하거나 미정으로 남겨 주세요.")
            if day is not None and (month is None or type(day) is not int or not 1 <= day <= calendar.monthrange(year, month)[1]):
                raise APIError(400, "해당 연도·월에 존재하는 일자를 입력하거나 일을 비워 주세요.")
            color = row.get("color", "red")
            if not isinstance(color, str) or color not in self.COLORS:
                raise APIError(400, "사건 색상을 확인해 주세요.")
            source_url = self.text(row, "source_url", 2000)
            if source_url:
                try:
                    source = urlsplit(source_url)
                    valid = (source.scheme in {"http", "https"} and source.hostname
                             and not source.username and not source.password
                             and not re.search(r"[\s\\]", source_url))
                except ValueError:
                    valid = False
                if not valid:
                    raise APIError(400, "출처는 올바른 http 또는 https 주소로 입력해 주세요.")
            events.append({"id": identifier, "year": year, "month": month, "day": day,
                           "title": self.text(row, "title", 160, required=True),
                           "description": self.text(row, "description", 6000), "color": color,
                           "date_label": self.text(row, "date_label", 80), "source_url": source_url})
        return {"title": title, "events": self.sort_events(events)}

    def save(self, payload):
        value = self.validate(payload)
        try:
            with self.locked():
                current = self.read_document()
                if current["version"] != payload["version"]:
                    raise APIError(409, "다른 창이나 Git에서 타임라인이 변경되었습니다. 입력 내용을 복사한 뒤 최신 타임라인을 불러와 주세요.")
                return self.write_source(value)
        except OSError:
            raise APIError(500, "타임라인 JSON을 저장하지 못했습니다. 파일 권한과 디스크 공간을 확인한 뒤 다시 시도해 주세요.") from None

    def handle(self, method, path, payload):
        if method == "GET" and path == "/__editor/api/timeline":
            return self.document()
        if method == "POST" and path == "/__editor/api/timeline/save":
            return self.save(payload)
        raise APIError(404, "요청한 타임라인 기능을 찾을 수 없습니다.")
