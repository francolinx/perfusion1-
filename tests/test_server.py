"""Server start-up behaviour. Run with:  python3 -m unittest discover -s tests -v"""
import os, socket, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from perfusion import server


class TestServerStartup(unittest.TestCase):
    def test_port_in_use_gives_plain_message(self):
        # On the DGX Spark used for bring-up, another program already held port 8080 and the
        # server died with a raw traceback. It must exit with a message that says what to do.
        blocker = socket.socket(); blocker.bind(("127.0.0.1", 0)); blocker.listen(1)
        port = blocker.getsockname()[1]
        try:
            with self.assertRaises(SystemExit) as cm:
                server.bind("127.0.0.1", port)
            self.assertIn(f"Port {port} is already in use", str(cm.exception.code))
            self.assertIn("PORT=", str(cm.exception.code))
        finally:
            blocker.close()

    def test_free_port_binds(self):
        srv = server.bind("127.0.0.1", 0)
        self.assertGreater(srv.server_address[1], 0)
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
