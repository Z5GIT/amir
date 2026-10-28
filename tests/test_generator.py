import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate.py"
spec = importlib.util.spec_from_file_location("generator", MODULE_PATH)
generator = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(generator)


class GeneratorTests(unittest.TestCase):
    def test_reality_vless_outbound_conversion(self):
        outbound = {
            "type": "vless",
            "server": "example.com",
            "server_port": 443,
            "uuid": "00000000-0000-0000-0000-000000000000",
            "flow": "xtls-rprx-vision",
            "tls": {
                "enabled": True,
                "server_name": "sni.example.com",
                "utls": {"enabled": True, "fingerprint": "chrome"},
                "reality": {"enabled": True, "public_key": "publicKey", "short_id": "ab"},
            },
        }
        uri = generator.vless_outbound_to_uri(outbound, "zoomjomedia 1")
        self.assertTrue(uri.startswith("vless://00000000-0000-0000-0000-000000000000@example.com:443?"))
        self.assertIn("security=reality", uri)
        self.assertIn("sni=sni.example.com", uri)
        self.assertIn("pbk=publicKey", uri)
        self.assertTrue(uri.endswith("#zoomjomedia%201"))

    def test_feed_with_metadata_header(self):
        data = '#profile-title: sample\n{ "outbounds": [{"type":"direct"}] }\n'
        parsed = generator.parse_json_feed(data)
        self.assertEqual(parsed, {"outbounds": [{"type": "direct"}]})

    def test_existing_vless_uri_only_renames_fragment(self):
        uri = "vless://00000000-0000-0000-0000-000000000000@host:443?security=tls&sni=example.com#old"
        rewritten = generator.rename_existing_vless_uri(uri, "zoomjomedia 2")
        self.assertEqual(rewritten, "vless://00000000-0000-0000-0000-000000000000@host:443?security=tls&sni=example.com#zoomjomedia%202")


if __name__ == "__main__":
    unittest.main()
