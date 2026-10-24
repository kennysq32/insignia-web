import base64
from io import BytesIO
import json
from unittest.mock import patch
import unittest
import yaml
import build
from content_editor import ContentEditor
from editor import APIError
import test_editor as fixture

class ContentTests(unittest.TestCase):
    setUp=fixture.EditorTests.setUp
    def prepare(self):
        self.cms=ContentEditor(build)
        build.STATIC.mkdir();(build.STATIC/'images').mkdir()
        for name in ('private','public','unused'):(build.STATIC/'images'/(name+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>'+name+'</text></svg>')
        (self.content/'pages').mkdir()
        (self.content/'gallery.yaml').write_text(yaml.safe_dump([{'id':'private','title':'SecretArtwork','image':'/images/private.svg','description':'NeverPublicGallery','draft':True},{'id':'public','title':'PublicArtwork','image':'/images/public.svg'}]))
        (self.content/'films.yaml').write_text(yaml.safe_dump([{'youtube':'WhWc3b3KhnY','title':'SecretFilm','draft':True},{'youtube':'eRsGyueVLvQ','title':'PublicFilm'}]))
        (self.content/'pages/about.md').write_text('---\ntitle: SecretAbout\ndraft: true\n---\nNeverPublicAbout')
        (self.content/'wiki/private.md').write_text('---\ntitle: SecretArchive\ndraft: true\ncustom: keep-me\n---\nNeverPublicArchive')
    def assert_not_public(self,words):
        for p in build.DIST.rglob('*'):
            if p.is_file() and p.suffix in {'.html','.json'} and not p.is_relative_to(build.DIST/'editor'):
                for word in words:self.assertNotIn(word,p.read_text(),str(p))
    def test_private_items_and_images_are_absent_from_public_output(self):
        self.prepare();build.Builder(editing=True).run()
        self.assert_not_public(['SecretArtwork','NeverPublicGallery','SecretFilm','SecretAbout','NeverPublicAbout','SecretArchive','NeverPublicArchive'])
        self.assertFalse((build.DIST/'images/private.svg').exists());self.assertFalse((build.DIST/'images/unused.svg').exists());self.assertTrue((build.DIST/'images/public.svg').exists())
        self.assertTrue((build.DIST/'editor/manage/index.html').exists());self.assertFalse((build.DIST/'about/index.html').exists())
        self.assertNotIn('href="/about/"',(build.DIST/'index.html').read_text())
        self.assertIn('SecretArtwork',[i['title'] for i in self.cms.catalog()['items']['gallery']])
    def test_publish_then_unpublish_media_preserves_metadata(self):
        self.prepare();doc=self.cms.document('gallery','0');doc['fields']['draft']=False;result=self.cms.save(doc)
        self.assertTrue((build.DIST/'images/private.svg').exists());self.assertIn('SecretArtwork',(build.DIST/'search.json').read_text())
        self.assertEqual(build.load_yaml(self.content/'gallery.yaml')[0]['id'],'private')
        result['document']['fields']['draft']=True;self.cms.save(result['document'])
        self.assertFalse((build.DIST/'images/private.svg').exists());self.assert_not_public(['SecretArtwork'])
    def test_section_hides_routes_navigation_feed_search_downloads(self):
        self.prepare();settings=self.cms.settings();settings['sections'].update(novel=False,gallery=False,films=False,wiki=False,about=False);self.cms.save_settings(settings)
        for folder in ['novel','gallery','films','wiki','about']:self.assertFalse((build.DIST/folder).exists(),folder)
        self.assertEqual(json.loads((build.DIST/'search.json').read_text()),[])
        for href in ['/novel/','/gallery/','/films/','/wiki/','/about/']:self.assertNotIn('href="'+href+'"',(build.DIST/'index.html').read_text())
        self.assertEqual(len(self.cms.catalog()['items']['books']),1)
        settings=self.cms.settings();settings['sections']['novel']=True;self.cms.save_settings(settings)
        self.assertTrue((build.DIST/'novel/test-book/첫-이야기/index.html').exists())
    def test_book_privacy_includes_chapters_and_editor_access(self):
        self.prepare();doc=self.cms.document('books','test-book');doc['fields']['draft']=True;self.cms.save(doc)
        self.assertFalse((build.DIST/'novel/test-book').exists());self.assertTrue(self.api.document('test-book')['fields']['draft'])
        self.assertIsNone(self.api.document('test-book',self.chapter.name)['read_url']);self.assertTrue(self.api.library()[0]['draft'])
    def test_page_archive_and_new_book_save_preserves_unknown_metadata(self):
        self.prepare();doc=self.cms.document('archive','private.md');doc['fields'].update(title='Updated Archive',body='**New text**',draft=False);self.cms.save(doc)
        self.assertEqual(build.read_markdown(self.content/'wiki/private.md')[0]['custom'],'keep-me')
        self.assertIn('<strong>New text</strong>',(build.DIST/'wiki/private/index.html').read_text())
        page=self.cms.document('pages','about.md');page['fields']['draft']=False;self.cms.save(page);self.assertTrue((build.DIST/'about/index.html').exists())
        result=self.cms.save({'kind':'books','new':True,'fields':{'title':'New Novel','draft':True}})
        self.assertTrue(result['document']['fields']['draft']);self.assertFalse((build.DIST/'novel/new-novel').exists())
    def test_conflicts_and_failed_build_preserve_existing_bytes(self):
        self.prepare();doc=self.cms.document('films','1');original=(self.content/'films.yaml').read_bytes();doc['fields']['title']='Modified'
        with patch.object(build.Builder,'run',side_effect=build.BuildError('broken')):
            with self.assertRaises(APIError):self.cms.save(doc)
        self.assertEqual((self.content/'films.yaml').read_bytes(),original);self.cms.save(doc)
        with self.assertRaises(APIError) as caught:self.cms.save(doc)
        self.assertEqual(caught.exception.status,409)
        stale=self.cms.settings();fresh=self.cms.settings();fresh['sections']['films']=False;self.cms.save_settings(fresh)
        with self.assertRaises(APIError) as caught:self.cms.save_settings(stale)
        self.assertEqual(caught.exception.status,409)
    def test_upload_verifies_bytes_and_stays_private_until_used(self):
        self.prepare()
        from PIL import Image
        stream=BytesIO();Image.new('RGB',(2,2),'red').save(stream,format='PNG')
        result=self.cms.upload({'data':base64.b64encode(stream.getvalue()).decode()});build.Builder(editing=True).run()
        self.assertFalse((build.DIST/result['url'].lstrip('/')).exists());path,mime=self.cms.media_file(result['url']);self.assertEqual(mime,'image/png');self.assertEqual(path.read_bytes(),stream.getvalue())
        for raw in [b'<svg onload="alert(1)"/>',b'not an image',b'\x89PNG\r\n\x1a\ninvalid']:
            with self.assertRaises(APIError):self.cms.upload({'data':base64.b64encode(raw).decode()})
        with self.assertRaises(APIError):self.cms.media_file('/images/../../content/site.yaml')
    def test_invalid_paths_types_and_settings_are_rejected(self):
        self.prepare()
        for kind,item in [('archive','../site.yaml'),('books','../escape'),('pages','/tmp/file.md'),('gallery','999')]:
            with self.subTest(kind=kind,item=item),self.assertRaises(APIError):self.cms.document(kind,item)
        doc=self.cms.document('films','0');doc['fields']['youtube']='javascript:alert(1)'
        with self.assertRaises(APIError):self.cms.save(doc)
        doc=self.cms.document('gallery','0');doc['fields']['image']='file:///etc/passwd'
        with self.assertRaises(APIError):self.cms.save(doc)
        settings=self.cms.settings();settings['sections']['gallery']='false'
        with self.assertRaises(APIError):self.cms.save_settings(settings)
        for kind in ('gallery','pages','books'):
            with self.assertRaises(APIError):self.cms.save({'kind':kind,'new':True,'fields':{'title':'New','draft':'false'}})
        (self.content/'wiki/escape.md').symlink_to(self.root/'book.txt')
        with self.assertRaises(APIError):self.cms.document('archive','escape.md')

    def test_failed_new_book_does_not_leave_a_public_empty_folder(self):
        self.prepare()
        with patch.object(build.Builder,'run',side_effect=build.BuildError('broken')):
            with self.assertRaises(APIError): self.cms.save({'kind':'books','new':True,'fields':{'title':'Failed Book','draft':True}})
        self.assertFalse((self.content/'novel/failed-book').exists())

    def test_http_content_catalog_and_private_media_require_gateway_secret(self):
        self.prepare();build.Builder(editing=True).run()
        from functools import partial
        import threading,os
        from urllib.request import urlopen,Request
        from urllib.error import HTTPError
        secret=self.root/'proxy-token';secret.write_text('s'*43)
        class Handler(build.DevHandler):
            editor=self.api
            base=''
        server=build.http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(build.DIST)))
        threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin=f'http://127.0.0.1:{server.server_port}'
        with patch.dict(os.environ,{'INSIGNIA_PROXY_TOKEN_FILE':str(secret)}):
            for route in ['/editor/manage/','/__editor/api/content/catalog','/__editor/media?path=/images/private.svg']:
                with self.subTest(route=route),self.assertRaises(HTTPError) as caught:urlopen(origin+route)
                self.assertEqual(caught.exception.code,403)
            headers={'X-Insignia-Proxy-Token':'s'*43}
            with urlopen(Request(origin+'/__editor/api/content/catalog',headers=headers)) as response:self.assertIn('items',json.load(response))
            with urlopen(Request(origin+'/__editor/media?path=/images/private.svg',headers=headers)) as response:self.assertEqual(response.headers['Content-Type'],'image/svg+xml')
            with self.assertRaises(HTTPError) as caught:urlopen(origin+'/images/private.svg')
            self.assertEqual(caught.exception.code,404)

    def test_each_content_kind_moves_to_trash_and_restores_as_private(self):
        self.prepare()
        for kind,item in [('gallery','1'),('films','1'),('archive','place.md'),('pages','about.md'),('books','test-book')]:
            with self.subTest(kind=kind):
                doc=self.cms.document(kind,item)
                result=self.cms.trash({'kind':kind,'id':item,'revision':doc['revision'],'action':'trash'})
                self.assertNotIn(item,[v['id'] for v in result['items'][kind]])
                deleted=next(v for v in result['trash'] if v['kind']==kind and v['id']==item)
                with self.assertRaises(APIError):self.cms.document(kind,item)
                result=self.cms.trash({**deleted,'action':'restore'})
                restored=self.cms.document(kind,item);self.assertTrue(restored['fields']['draft'])
                self.assertNotIn(item,[v['id'] for v in result['trash'] if v['kind']==kind])
        self.assertEqual(build.load_yaml(self.book)['custom'],'preserve-me')

    def test_chapter_trash_hides_it_from_readers_and_manuscript_library(self):
        self.prepare();doc=self.api.document('test-book',self.chapter.name)
        result=self.cms.trash({'kind':'chapters','id':'test-book/'+self.chapter.name,'revision':doc['revision'],'action':'trash'})
        self.assertFalse((build.DIST/'novel/test-book/첫-이야기').exists())
        self.assertNotIn(self.chapter.name,[c['id'] for c in self.api.library()[0]['chapters']])
        with self.assertRaises(APIError):self.api.document('test-book',self.chapter.name)
        deleted=next(i for i in result['trash'] if i['kind']=='chapters')
        self.cms.trash({**deleted,'action':'restore'})
        self.assertTrue(self.api.document('test-book',self.chapter.name)['fields']['draft'])
        self.assertFalse((build.DIST/'novel/test-book/첫-이야기').exists())

    def test_trash_and_restore_have_revision_checks_and_failed_build_rollback(self):
        self.prepare();doc=self.cms.document('gallery','1');payload={'kind':'gallery','id':'1','revision':doc['revision'],'action':'trash'}
        original=(self.content/'gallery.yaml').read_bytes()
        with patch.object(build.Builder,'run',side_effect=build.BuildError('broken')):
            with self.assertRaises(APIError):self.cms.trash(payload)
        self.assertEqual((self.content/'gallery.yaml').read_bytes(),original)
        with self.assertRaises(APIError):self.cms.trash({**payload,'action':'restore'})
        self.cms.trash(payload)
        with self.assertRaises(APIError) as caught:self.cms.trash(payload)
        self.assertEqual(caught.exception.status,409)
        self.assertFalse((build.DIST/'images/public.svg').exists())
        for item in ['../chapter.md','test-book/../../site.yaml','test-book/_book.yaml']:
            with self.assertRaises(APIError):self.cms.trash({'kind':'chapters','id':item,'revision':'bad','action':'trash'})
