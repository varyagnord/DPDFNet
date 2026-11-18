"""Check preview admission without opening a device."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import xdna2_preview


class PreviewAdmission(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary) / "lab"
        self.root.mkdir()
        payload = b"known test asset"
        self.asset = self.root / "asset.bin"
        self.asset.write_bytes(payload)
        self.spec = dict(path=self.asset.name, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        choice = dict(library=self.spec, model=self.spec, manifest=self.spec, commands_per_frame=3)
        catalog = dict(owner=self.spec, models={"2": dict(default="test", profiles={"test": choice})})
        path = self.root / "preview.json"
        path.write_text(json.dumps(catalog))
        self.enterContext(patch.object(xdna2_preview, "CATALOG", path))

    def test_exact_assets_and_default_profile(self):
        name, assets, commands = xdna2_preview.bindings(self.root, 2, None)
        self.assertEqual((name, commands), ("test", 3))
        self.assertEqual(assets, dict.fromkeys(("owner", "library", "manifest", "model"), self.asset))

    def test_reject_unknown_profile(self):
        with self.assertRaisesRegex(ValueError, "supports these"):
            xdna2_preview.bindings(self.root, 2, "missing")

    def test_reject_same_size_modified_file(self):
        self.asset.write_bytes(b"x" * self.spec["bytes"])
        with self.assertRaisesRegex(ValueError, "file changed"):
            xdna2_preview.bindings(self.root, 2, None)

    def test_reject_external_symlink(self):
        self.asset.unlink()
        other = self.root.parent / self.asset.name
        other.write_bytes(b"known test asset")
        self.asset.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "Unexpected preview file"):
            xdna2_preview.bindings(self.root, 2, None)


if __name__ == "__main__":
    unittest.main()
