from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from tsa.rpc import Node, RpcError


class Handler(BaseHTTPRequestHandler):
    requests = []
    mode = 'redirect'

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.requests.append(self.path)
        self.rfile.read(int(self.headers['Content-Length']))
        if self.mode == 'disconnect':
            self.close_connection = True
            return
        self.send_response(307)
        self.send_header('Location', '/second-send')
        self.send_header('Content-Length', '0')
        self.end_headers()


class TransportTests(unittest.TestCase):
    def test_broadcast_is_not_replayed_after_redirect_or_lost_response(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            node = Node('http://127.0.0.1:' + str(server.server_port), 'structstestnet-111', timeout=1)
            for mode in ('redirect', 'disconnect'):
                Handler.mode, Handler.requests = mode, []
                with self.subTest(mode=mode), self.assertRaises(RpcError):
                    node.broadcast(b'previously persisted bytes')
                self.assertEqual(Handler.requests, ['/'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
