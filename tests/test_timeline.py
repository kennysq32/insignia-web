"""Exercise durable chronology saves, concurrent edits, and the private HTTP gate."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import build
from editor import APIError, EditorAPI
from timeline import TimelineAPI
import test_editor as fixture


def save_in_process(root, payload, barrier, results):
    with patch.object(build, "ROOT", Path(root)):
        barrier.wait(timeout=15)
        try:
            results.put(TimelineAPI(build).save(payload)["version"])
        except APIError as error:
            results.put(error.status)


class TimelineTests(unittest.TestCase):
    setUp = fixture.EditorTests.setUp

    def event(self, identifier="first", year=2140, month=3, day=None, **changes):
        return {"id": identifier, "year": year, "month": month, "day": day,
                "title": "첫 번째 사건", "description": "사건 설명", "color": "red", **changes}

    def timeline(self):
        return TimelineAPI(build)

    def save(self, events, version=0):
        return self.timeline().save({"title": "테스트 세계관", "version": version, "events": events})

    def test_empty_timeline_then_durable_sorted_round_trip(self):
        self.assertEqual(self.timeline().document()["version"], 0)
        events = [self.event("last", 3000), self.event("day", 2140, 3, 2), self.event("month"),
                  self.event("earlier-month", 2140, 1), self.event("negative", -100), self.event("zero", 0)]
        saved = self.save(events)
        self.assertEqual([row["id"] for row in saved["events"]],
                         ["negative", "zero", "earlier-month", "month", "day", "last"])
        self.assertEqual(self.timeline().document(), saved)
        self.assertTrue((self.root / "timeline-data/timeline.json").is_file())
        self.assertFalse((self.root / ".private/timeline.sqlite3").exists())
        self.assertRegex(saved["version"], r"^[0-9a-f]{64}$")
        self.assertIsNone(next(row for row in saved["events"] if row["id"] == "month")["day"])

    def test_update_dates_and_delete_persist_across_new_instances(self):
        saved = self.save([self.event(), self.event("second", 2139, 12, 31)])
        saved["events"][1].update(year=2138, month=2, day=28)
        result = self.timeline().save(saved)
        self.assertEqual(result["events"][0]["id"], "first")
        result["events"] = []
        empty = self.timeline().save(result)
        self.assertEqual(self.timeline().document()["events"], [])
        self.assertEqual(len({saved["version"], result["version"], empty["version"]}), 3)

    def test_unknown_month_and_approximate_dates_keep_source_precision(self):
        source = "https://insignia-wiki.mastercable-cloud.site/timeline/#timeline-event-8"
        saved = self.save([self.event("dated", 1990, 1, 1),
                           self.event("year-only", 1990, None),
                           self.event("approximate", 1990, None, date_label="1990년대 초", source_url=source)])
        self.assertEqual([row["id"] for row in saved["events"]], ["approximate", "year-only", "dated"])
        approximate = self.timeline().document()["events"][0]
        self.assertIsNone(approximate["month"])
        self.assertIsNone(approximate["day"])
        self.assertEqual(approximate["date_label"], "1990년대 초")
        self.assertEqual(approximate["source_url"], source)
        saved["events"][0]["title"] = "수정한 사건"
        updated = self.timeline().save(saved)
        self.assertEqual(updated["events"][0]["source_url"], source)
        self.assertEqual(updated["events"][0]["date_label"], "1990년대 초")

    def test_unknown_month_rejects_day_and_source_links_are_safe(self):
        for changes in ({"month": None, "day": 1}, {"date_label": []}, {"date_label": "x" * 81},
                        {"source_url": "javascript:alert(1)"}, {"source_url": "//evil.test/"},
                        {"source_url": "https://name:password@example.test/"},
                        {"source_url": "https://example.test/\npath"}, {"source_url": []}):
            with self.subTest(changes=changes), self.assertRaises(APIError):
                self.save([self.event(**changes)])
        self.assertEqual(self.timeline().document()["version"], 0)

    def test_stale_version_never_overwrites_data(self):
        saved = self.save([self.event()])
        with self.assertRaises(APIError) as caught:
            self.save([], 0)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.timeline().document(), saved)

    def test_concurrent_saves_accept_only_one_writer(self):
        self.timeline().document()
        barrier = threading.Barrier(2)
        def write(identifier):
            barrier.wait()
            try:
                return self.save([self.event(identifier)])["version"]
            except APIError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["one", "two"]))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(sum(isinstance(result, str) for result in results), 1)
        self.assertEqual(len(self.timeline().document()["events"]), 1)

    def test_separate_server_processes_cannot_overwrite_one_another(self):
        context = multiprocessing.get_context("spawn")
        barrier, results = context.Barrier(2), context.Queue()
        processes = []
        for identifier in ("one", "two"):
            payload = {"title": "Concurrent", "version": 0, "events": [self.event(identifier)]}
            process = context.Process(target=save_in_process, args=(str(self.root), payload, barrier, results))
            process.start()
            processes.append(process)
        try:
            outcomes = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(outcomes.count(409), 1)
            self.assertEqual(len(self.timeline().document()["events"]), 1)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
            results.close()

    def test_json_is_readable_stable_and_restores_without_runtime_state(self):
        saved = self.save([self.event("approx", 1990, None, date_label="1990년대 초",
                                      source_url="https://example.test/timeline/#event")])
        path = self.root / "timeline-data/timeline.json"
        raw = path.read_bytes()
        self.assertIn("첫 번째 사건", raw.decode("utf-8"))
        value = json.loads(raw)
        self.assertEqual(value["schema_version"], 1)
        self.assertNotIn("version", value)
        self.assertNotIn("updated_at", value)
        self.assertTrue(raw.endswith(b"\n"))
        unchanged = self.timeline().save(saved)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(unchanged["version"], saved["version"])
        checkout = self.root / "fresh-checkout"
        (checkout / "timeline-data").mkdir(parents=True)
        (checkout / "timeline-data/timeline.json").write_bytes(raw)
        with patch.object(build, "ROOT", checkout):
            restored = self.timeline().document()
        self.assertEqual(restored["events"], saved["events"])
        self.assertEqual(restored["version"], saved["version"])

    def test_git_restores_and_hand_edits_are_authoritative_and_detect_conflicts(self):
        first = self.save([self.event()])
        path = self.root / "timeline-data/timeline.json"
        initial = path.read_bytes()
        second = self.save([self.event(), self.event("later", 2150)], first["version"])
        path.write_bytes(initial)  # Equivalent to checking out the earlier JSON.
        restored = self.timeline().document()
        self.assertEqual(restored["events"], first["events"])
        with self.assertRaises(APIError) as caught:
            self.timeline().save(second)
        self.assertEqual(caught.exception.status, 409)
        edited = json.loads(initial)
        edited["title"] = "Manually edited on another branch"
        path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(APIError) as caught:
            self.timeline().save(first)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.timeline().document()["title"], edited["title"])

    def test_legacy_sqlite_migrates_once_without_changing_original_database(self):
        legacy = self.root / ".private/timeline.sqlite3"
        legacy.parent.mkdir()
        value = {"title": "기존 세계관", "events": [self.event("legacy", 1990, None, date_label="1990년대 초")]}
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("CREATE TABLE timeline (id INTEGER PRIMARY KEY, version INTEGER, data TEXT, updated_at TEXT)")
            db.execute("INSERT INTO timeline VALUES (1, 27, ?, '2026-10-29T00:00:00Z')", (json.dumps(value, ensure_ascii=False),))
        original = legacy.read_bytes()
        migrated = self.timeline().document()
        self.assertEqual(migrated["title"], value["title"])
        self.assertEqual(migrated["events"][0]["id"], "legacy")
        self.assertEqual(migrated["events"][0]["date_label"], "1990년대 초")
        self.assertEqual(legacy.read_bytes(), original)
        path = self.root / "timeline-data/timeline.json"
        path.unlink()
        with self.assertRaises(APIError) as caught:
            self.timeline().document()
        self.assertEqual(caught.exception.status, 500)
        self.assertFalse(path.exists())  # Never resurrect the stale SQLite backup.

    def test_invalid_json_and_schema_never_fall_back_or_overwrite_source(self):
        saved = self.save([self.event()])
        path = self.root / "timeline-data/timeline.json"
        for raw in (b"<<<<<<< HEAD\n{}", b"[]", b'{"schema_version":2}',
                    b'{"schema_version":1,"title":"Bad","events":[{}]}'):
            path.write_bytes(raw)
            for operation in (self.timeline().document, lambda: self.timeline().save(saved)):
                with self.subTest(raw=raw), self.assertRaises(APIError) as caught:
                    operation()
                self.assertEqual(caught.exception.status, 500)
                self.assertEqual(path.read_bytes(), raw)

    def test_failed_atomic_write_keeps_previous_json_and_revision(self):
        saved = self.save([self.event()])
        path = self.root / "timeline-data/timeline.json"
        original = path.read_bytes()
        with patch.object(EditorAPI, "atomic_write", side_effect=OSError("disk full")):
            with self.assertRaises(APIError) as caught:
                self.save([], saved["version"])
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.timeline().document(), saved)

    def test_calendar_validation_and_arbitrary_fictional_years(self):
        saved = self.save([self.event("leap", 2000, 2, 29), self.event("fiction", 12000, 2, 29),
                           self.event("negative", -400, 2, 29), self.event("no-day", 1900, 2)])
        for changes in ({"year": 1900, "month": 2, "day": 29}, {"month": 4, "day": 31},
                        {"month": 0}, {"month": 13}, {"day": 0}, {"day": -1}, {"day": 1.5},
                        {"year": True}, {"month": True}, {"day": True}, {"year": 1000000}, {"year": "2140"}):
            with self.subTest(changes=changes), self.assertRaises(APIError):
                self.save([self.event(**changes)], saved["version"])
            self.assertEqual(self.timeline().document(), saved)

    def test_invalid_payload_cannot_replace_saved_timeline(self):
        saved = self.save([self.event()])
        invalid_events = [None, {}, [None], [self.event(), self.event()], [self.event(id="../escape")],
                          [self.event(title=" ")], [self.event(title="x" * 161)],
                          [self.event(description=[])], [self.event(description="x" * 6001)],
                          [self.event(color="url(evil)")], [self.event(color=[])], [self.event()] * 2001]
        for events in invalid_events:
            with self.subTest(events=str(events)[:80]), self.assertRaises(APIError):
                self.save(events, saved["version"])
        for changes in ({"version": True}, {"version": -1}, {"title": ""}, {"title": "x" * 121}):
            with self.subTest(changes=changes), self.assertRaises(APIError):
                self.timeline().save({**saved, **changes})
        self.assertEqual(self.timeline().document(), saved)

    def test_static_build_never_contains_timeline_data_or_editor(self):
        self.save([self.event(title="PrivateChronologyCanary", description="PrivateEventDescription")])
        build.Builder().run()
        self.assertFalse((build.DIST / "editor/timeline").exists())
        self.assertFalse((build.DIST / "timeline-data").exists())
        build.Builder(editing=True).run()
        self.assertTrue((build.DIST / "editor/timeline/index.html").is_file())
        for path in build.DIST.rglob("*"):
            if path.is_file():
                self.assertNotEqual(path.suffix, ".sqlite3")
                if path.suffix in {".html", ".json", ".js"}:
                    self.assertNotIn("PrivateChronologyCanary", path.read_text())
                    self.assertNotIn("PrivateEventDescription", path.read_text())

    def server(self, base=""):
        class Handler(build.DevHandler):
            editor = EditorAPI(build)
        Handler.base = base
        server = build.http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(build.DIST)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_http_gateway_protects_canvas_reads_writes_and_encoded_paths(self):
        build.Builder(editing=True).run()
        origin = self.server()
        secret = self.root / "proxy-token"
        secret.write_text("t" * 43)
        routes = ["/editor/timeline/", "/%65ditor/timeline/", "/x%2f..%2feditor/timeline/",
                  "/__editor/api/timeline", "/%5f_editor/api/timeline"]
        with patch.dict(os.environ, {"INSIGNIA_PROXY_TOKEN_FILE": str(secret)}):
            for method in ("GET", "HEAD"):
                for route in routes:
                    with self.subTest(method=method, route=route), self.assertRaises(HTTPError) as caught:
                        urlopen(Request(origin + route, method=method))
                    self.assertEqual(caught.exception.code, 403)
            payload = json.dumps({"title": "Private", "version": 0, "events": [self.event()]}).encode()
            headers = {"Content-Type": "application/json", "X-Insignia-Editor": "1", "Origin": origin}
            for changes in ({}, {"X-Insignia-Proxy-Token": "forged"},
                            {"X-Insignia-Proxy-Token": "t" * 43, "Origin": "http://evil.test"}):
                with self.subTest(changes=changes), self.assertRaises(HTTPError) as caught:
                    urlopen(Request(origin + "/__editor/api/timeline/save", data=payload, headers={**headers, **changes}))
                self.assertEqual(caught.exception.code, 403)
            self.assertEqual(self.timeline().document()["version"], 0)
            with urlopen(Request(origin + "/__editor/api/timeline", headers={"X-Insignia-Proxy-Token": "t" * 43})) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(json.load(response)["events"], [])

    def test_http_round_trip_with_base_path_and_invalid_json(self):
        origin = self.server("/preview")
        api = origin + "/preview/__editor/api/timeline"
        with urlopen(api) as response:
            payload = json.load(response)
        payload["events"] = [self.event()]
        headers = {"Content-Type": "application/json", "X-Insignia-Editor": "1", "Origin": origin}
        with urlopen(Request(api + "/save", data=json.dumps(payload).encode(), headers=headers)) as response:
            saved = json.load(response)
        self.assertEqual(saved["events"][0]["title"], "첫 번째 사건")
        for body in (b"null", b"[]", b"{broken", b"{}"):
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                urlopen(Request(api + "/save", data=body, headers=headers))
            self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.timeline().document(), saved)


if __name__ == "__main__":
    unittest.main()
