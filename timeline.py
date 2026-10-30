"""Private world-building timeline, persisted separately from public content."""

from __future__ import annotations

import calendar
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import sqlite3
from urllib.parse import urlsplit

from editor import APIError


class TimelineAPI:
    COLORS = {"red", "blue", "green", "gray"}

    def __init__(self, site):
        self.site = site

    @contextmanager
    def database(self):
        folder = self.site.ROOT / ".private"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(folder / "timeline.sqlite3", timeout=10)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS timeline (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            yield db
        finally:
            db.close()

    @staticmethod
    def sort_events(events):
        return sorted(events, key=lambda e: (e["year"], e["month"] or 0, e["day"] or 0, e["id"]))

    def document(self):
        with self.database() as db:
            row = db.execute("SELECT version, data, updated_at FROM timeline WHERE id = 1").fetchone()
        if row is None:
            return {"version": 0, "title": "세계관 타임라인", "events": [], "updated_at": None}
        return {**json.loads(row[1]), "version": row[0], "updated_at": row[2]}

    @staticmethod
    def text(data, key, limit, required=False):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise APIError(400, "제목과 설명의 길이·형식을 확인해 주세요.")
        return value.strip()

    def validate(self, payload):
        if type(payload.get("version")) is not int or payload["version"] < 0:
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
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.database() as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT version FROM timeline WHERE id = 1").fetchone()
                version = row[0] if row else 0
                if version != payload["version"]:
                    raise APIError(409, "다른 창에서 타임라인이 변경되었습니다. 입력 내용을 복사한 뒤 최신 타임라인을 불러와 주세요.")
                version += 1
                db.execute("""INSERT INTO timeline (id, version, data, updated_at) VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET version=excluded.version,
                    data=excluded.data, updated_at=excluded.updated_at""",
                           (version, json.dumps(value, ensure_ascii=False), now))
        return {**value, "version": version, "updated_at": now}

    def handle(self, method, path, payload):
        if method == "GET" and path == "/__editor/api/timeline":
            return self.document()
        if method == "POST" and path == "/__editor/api/timeline/save":
            return self.save(payload)
        raise APIError(404, "요청한 타임라인 기능을 찾을 수 없습니다.")
