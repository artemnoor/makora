import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from makora_core.iterations import IterationStore
from makora_core.server import MakoraHandler


def zip_bytes(files):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,data in files.items(): archive.writestr(path,data)
    return output.getvalue()


class IterationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.workspace=Path(cls.temp.name)/'workspace';cls.workspace.mkdir()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),lambda *a,**kw:MakoraHandler(*a,directory=None,**kw))
        cls.http.iteration_store=IterationStore(cls.workspace)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.http.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.temp.cleanup()

    def call(self,path,body=None,content_type='application/json'):
        request=urllib.request.Request(self.base+path,data=body,headers={'Content-Type':content_type} if body is not None else {},method='POST' if body is not None else 'GET')
        try:
            with urllib.request.urlopen(request) as response:return response.status,response.headers,response.read()
        except urllib.error.HTTPError as error:return error.code,error.headers,error.read()

    def test_http_api_prepare_compare_decide_history_and_safe_rejection(self):
        basezip=zip_bytes({'src/app.js':'v1','mocks/fixtures/places.json':'[]'})
        status,headers,body=self.call('/api/status')
        self.assertEqual(status,200);self.assertTrue(json.loads(body)['result']['available'])
        status,_,body=self.call('/api/iterations/prepare',basezip,'application/zip')
        self.assertEqual(status,201)
        created=json.loads(body)['result'];iteration=created['iterations'][0]['iteration_id']
        changed=zip_bytes({'src/app.js':'v2','mocks/fixtures/places.json':'[]'})
        status,_,body=self.call(f'/api/iterations/{iteration}/result',changed,'application/zip')
        self.assertEqual(status,200)
        result=json.loads(body)['result']
        change=next(entry for entry in result['changes'] if entry['path']=='src/app.js')
        status,_,body=self.call(f'/api/iterations/{iteration}/decisions/{change["id"]}',json.dumps({'action':'accept'}).encode())
        self.assertEqual(status,200)
        status,_,body=self.call('/api/history')
        history=json.loads(body)['result']
        self.assertEqual(history['iterations'][0]['changes'][0]['decision'],'accepted')
        questions=result['questions']
        if questions:
            answers={q['id']:'Reviewed' for q in questions}
            status,_,body=self.call(f'/api/iterations/{iteration}/questions',json.dumps({'answers':answers}).encode())
            self.assertEqual(status,200)
        status,_,body=self.call(f'/api/iterations/{iteration}/approve',b'{}')
        self.assertEqual(status,409)  # code path changes stage 03 docs; adapter must return docs first
        slip=zip_bytes({'../outside.txt':'x'})
        status,_,body=self.call(f'/api/iterations/{iteration}/result',slip,'application/zip')
        self.assertEqual(status,400)
        self.assertEqual(json.loads(body)['error']['code'],'UNSAFE_ARCHIVE_PATH')
        cross_origin=urllib.request.Request(self.base+'/api/iterations/prepare',data=basezip,
            headers={'Content-Type':'application/zip','Origin':'https://untrusted.example'},method='POST')
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(cross_origin)
        self.assertEqual(denied.exception.code,403)


if __name__=='__main__':unittest.main()
