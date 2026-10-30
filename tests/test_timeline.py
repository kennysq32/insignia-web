"""Exercise durable chronology saves, concurrent edits, and the private HTTP gate."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import build
from editor import APIError, EditorAPI
from timeline import TimelineAPI
import test_editor as fixture


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
        self.assertTrue((self.root / ".private/timeline.sqlite3").is_file())
        self.assertIsNone(next(row for row in saved["events"] if row["id"] == "month")["day"])

    def test_update_dates_and_delete_persist_across_new_instances(self):
        saved = self.save([self.event(), self.event("second", 2139, 12, 31)])
        saved["events"][1].update(year=2138, month=2, day=28)
        result = self.timeline().save(saved)
        self.assertEqual(result["events"][0]["id"], "first")
        result["events"] = []
        empty = self.timeline().save(result)
        self.assertEqual(self.timeline().document()["events"], [])
        self.assertEqual(empty["version"], 3)

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
        self.assertEqual(sorted(results), [1, 409])
        self.assertEqual(len(self.timeline().document()["events"]), 1)

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
