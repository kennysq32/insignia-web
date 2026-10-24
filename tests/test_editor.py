"""Exercise real file saves/builds against an isolated manuscript library."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import build
from editor import APIError, EditorAPI


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / "content"
        folder = self.content / "novel" / "test-book"
        folder.mkdir(parents=True)
        (self.content / "wiki").mkdir()
        (self.content / "wiki" / "place.md").write_text("---\ntitle: 장소\n---\n도시입니다.", encoding="utf-8")
        (self.content / "site.yaml").write_text("title: Test\nauthor: Writer\nxtc: false\n", encoding="utf-8")
        self.book = folder / "_book.yaml"
        self.book.write_text("title: 테스트 책\norder: 7\ncustom: preserve-me\n", encoding="utf-8")
        self.chapter = folder / "01-첫-이야기.md"
        self.original = "---\ntitle: First Story\ncustom: keep\ndate: 2026-10-24\n---\n원래 원고.\n".encode()
        self.chapter.write_bytes(self.original)
        self.draft = folder / "02-미공개.md"
        self.draft.write_text("---\ndraft: true\n---\n비공개 원고", encoding="utf-8")
        shutil.copytree(build.TEMPLATES, self.root / "templates")
        shutil.copytree(build.ASSETS, self.root / "assets")
        self.patcher = patch.multiple(build, ROOT=self.root, CONTENT=self.content, DIST=self.root / "dist",
                                      STATIC=self.root / "static", TEMPLATES=self.root / "templates",
                                      ASSETS=self.root / "assets", XTC_CACHE=self.root / ".cache" / "xtc")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.api = EditorAPI(build)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def payload(self):
        doc = self.api.document("test-book", self.chapter.name)
        return {"book": doc["book"], "chapter": doc["chapter"], "revision": doc["revision"], "fields": doc["fields"]}

    def test_save_preserves_metadata_and_url_and_backs_up_exact_source(self):
        payload = self.payload()
        payload["fields"].update(title="고친 제목", body="**새 원고**\n[[장소]]", alternate_title="New Story")
        result = self.api.save(payload)
        meta, body = build.read_markdown(self.chapter)
        self.assertEqual(meta["custom"], "keep")
        self.assertEqual(meta["heading"], "고친 제목")
        self.assertEqual(meta["title"], "New Story")
        self.assertEqual(body, "**새 원고**\n[[장소]]")
        self.assertEqual(result["document"]["read_url"], "/novel/test-book/첫-이야기/")
        page = (build.DIST / "novel/test-book/첫-이야기/index.html").read_text(encoding="utf-8")
        self.assertIn("고친 제목", page)
        self.assertIn("<strong>새 원고</strong>", page)
        backup = next((self.root / ".cache/editor/test-book").iterdir())
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertNotEqual(payload["revision"], result["document"]["revision"])

    def test_stale_revision_never_overwrites_external_edit(self):
        payload = self.payload()
        self.chapter.write_bytes(self.original + "외부 수정".encode())
        with self.assertRaises(APIError) as caught:
            self.api.save(payload)
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(self.chapter.read_bytes().endswith("외부 수정".encode()))

    def test_failed_build_rolls_back_exact_file_bytes(self):
        payload = self.payload()
        payload["fields"]["body"] = "반영되면 안 되는 원고"
        with patch.object(build.Builder, "run", side_effect=build.BuildError("broken template")):
            with self.assertRaises(APIError):
                self.api.save(payload)
        self.assertEqual(self.chapter.read_bytes(), self.original)

    def test_new_draft_can_be_reopened_and_published(self):
        fields = {"title": "새로운 이야기", "body": "새로 쓴 원고", "draft": True}
        result = self.api.save({"book": "test-book", "new": True, "fields": fields})
        doc = result["document"]
        self.assertTrue(doc["fields"]["draft"])
        self.assertIsNone(doc["read_url"])
        self.assertFalse((build.DIST / "novel/test-book/새로운-이야기").exists())
        doc["fields"]["draft"] = False
        published = self.api.save({"book": doc["book"], "chapter": doc["chapter"], "revision": doc["revision"], "fields": doc["fields"]})
        self.assertEqual(published["document"]["read_url"], "/novel/test-book/새로운-이야기/")
        self.assertTrue((build.DIST / "novel/test-book/새로운-이야기/index.html").exists())

    def test_duplicate_new_titles_get_distinct_urls(self):
        payload = {"book": "test-book", "new": True, "fields": {"title": "첫 이야기", "body": "", "draft": True}}
        result = self.api.save(payload)
        self.assertIn("첫-이야기-2", result["document"]["chapter"])

    def test_book_save_keeps_unedited_fields(self):
        doc = self.api.document("test-book")
        doc["fields"].update(title="새 책 제목", genres="판타지, 정치", synopsis="새 **책 소개**")
        self.api.save({"book": doc["book"], "revision": doc["revision"], "fields": doc["fields"]})
        meta = build.load_yaml(self.book)
        self.assertEqual(meta["order"], 7)
        self.assertEqual(meta["custom"], "preserve-me")
        self.assertEqual(meta["genres"], ["판타지", "정치"])

    def test_preview_matches_reader_wiki_links_and_footnotes(self):
        result = self.api.preview({"fields": {"body": "**강조**\n다음 줄 [[장소]][^1]\n\n[^1]: 각주"}})
        self.assertIn("<strong>강조</strong>", result["html"])
        self.assertIn('href="/wiki/place/"', result["html"])
        self.assertIn("각주", result["notes"])

    def test_path_traversal_and_symlinks_are_rejected(self):
        for book, chapter in (("..", None), ("test-book/..", None), ("test-book", "../../site.md"),
                              ("test-book", "..\\site.md"), ("test-book", "_book.yaml")):
            with self.subTest(book=book, chapter=chapter), self.assertRaises(APIError):
                self.api.document(book, chapter)
        try:
            (self.content / "novel" / "escape").symlink_to(self.root, target_is_directory=True)
        except OSError:
            return  # Windows may not grant symbolic-link privileges.
        with self.assertRaises(APIError):
            self.api.document("escape")

    def test_invalid_input_never_changes_source(self):
        for changes in ({"title": " "}, {"date": "2026-02-30"}, {"draft": "false"}, {"body": []}):
            payload = self.payload()
            payload["fields"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(APIError):
                self.api.save(payload)
            self.assertEqual(self.chapter.read_bytes(), self.original)

    def test_local_origin_and_json_header_required(self):
        valid = {"Host": "localhost:8000", "Origin": "http://localhost:8000", "Content-Type": "application/json", "X-Insignia-Editor": "1"}
        self.api.check_request(valid, 8000, "POST")
        for changes in ({"Host": "evil.test:8000"}, {"Origin": "http://evil.test"}, {"X-Insignia-Editor": ""}, {"Content-Type": "text/plain"}):
            with self.subTest(changes=changes), self.assertRaises(APIError):
                self.api.check_request({**valid, **changes}, 8000, "POST")

    def test_private_gateway_requires_secret_even_for_loopback_reads(self):
        secret = self.root / "proxy-token"
        secret.write_text("a" * 43)
        valid = {"Host": "novel:8000", "Origin": "http://novel:8000", "X-Insignia-Proxy-Token": "a" * 43,
                 "Content-Type": "application/json", "X-Insignia-Editor": "1"}
        with patch.dict(os.environ, {"INSIGNIA_PROXY_TOKEN_FILE": str(secret)}):
            self.api.check_request(valid, 8000, "POST")
            for method in ("GET", "HEAD", "POST"):
                for actual in ("", "b" * 43):
                    with self.subTest(method=method, actual=actual), self.assertRaises(APIError):
                        self.api.check_request({**valid, "Host": "localhost:8000", "X-Insignia-Proxy-Token": actual}, 8000, method)
            with self.assertRaises(APIError):
                self.api.check_request({**valid, "Origin": "https://evil.test"}, 8000, "POST")

    def test_http_private_editor_rejects_encoded_paths_and_head_without_secret(self):
        secret = self.root / "proxy-token"
        secret.write_text("a" * 43)
        build.Builder(editing=True).run()
        class Handler(build.DevHandler):
            editor = self.api
            base = ""
        server = build.http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(build.DIST)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        with patch.dict(os.environ, {"INSIGNIA_PROXY_TOKEN_FILE": str(secret)}):
            with urlopen(origin + "/") as response:
                self.assertEqual(response.status, 200)
            for method in ("GET", "HEAD"):
                for path in ("/editor/", "/%65ditor/", "/%2feditor/", "/x%2f..%2feditor/", "/__editor/api/library"):
                    with self.subTest(method=method, path=path), self.assertRaises(HTTPError) as caught:
                        urlopen(Request(origin + path, method=method))
                    self.assertEqual(caught.exception.code, 403)
            with urlopen(Request(origin + "/__editor/api/library", headers={"X-Insignia-Proxy-Token": "a" * 43})) as response:
                self.assertIn("books", json.load(response))

    def test_static_build_excludes_editor_and_draft_chapters(self):
        build.Builder().run()
        self.assertFalse((build.DIST / "editor").exists())
        self.assertFalse((build.DIST / "novel/test-book/미공개").exists())
        self.assertNotIn("소설 편집", (build.DIST / "index.html").read_text(encoding="utf-8"))
        build.Builder(editing=True).run()
        self.assertTrue((build.DIST / "editor/index.html").exists())

    def test_http_round_trip_and_rejected_cross_origin(self):
        class Handler(build.DevHandler):
            editor = self.api
            base = "/preview"

        server = build.http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(build.DIST)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        query = urlencode({"book": "test-book", "chapter": self.chapter.name})
        with urlopen(origin + "/preview/__editor/api/document?" + query) as response:
            doc = json.load(response)
        doc["fields"]["body"] = "HTTP로 저장한 한국어 원고"
        payload = {"book": doc["book"], "chapter": doc["chapter"], "revision": doc["revision"], "fields": doc["fields"]}
        headers = {"Content-Type": "application/json", "X-Insignia-Editor": "1", "Origin": origin}
        request = Request(origin + "/preview/__editor/api/save", data=json.dumps(payload).encode(), headers=headers)
        with urlopen(request) as response:
            saved = json.load(response)
        self.assertEqual(saved["document"]["fields"]["body"], doc["fields"]["body"])
        request = Request(origin + "/preview/__editor/api/preview", data=b"{}", headers={**headers, "Origin": "http://evil.test"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
