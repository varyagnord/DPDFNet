"""Check catalog relocation and failed staging without accelerator access."""

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SCRIPT = (Path(__file__).resolve().parents[1]
          / "research/xdna2_preview/spectral/stage_local_pcm.py")
spec = importlib.util.spec_from_file_location("stage_local_pcm", SCRIPT)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class CatalogStaging(unittest.TestCase):
    def prepare_input(self, root):
        models = {}
        for number in (2, 8):
            source = root / f"original{number}"
            source.mkdir()
            model = source / "model.onnx"
            model.write_bytes(bytes((number,)))
            library = source / "provider.so"
            library.write_bytes(b"library")
            manifest = source / "assets.json"
            manifest.write_text(json.dumps({"models": [
                {"model": number, "asset": {"path": model.name, "bytes": 1,
                                             "sha256": stage.digest(model)}}]}))
            row = {}
            for key, path in (("model", model), ("library", library), ("manifest", manifest)):
                row[key] = str(path)
                row[f"{key}_sha256"] = stage.digest(path)
            models[str(number)] = row | {"compact_close": True}
        provider = root / "providers.json"
        provider.write_text(json.dumps({"version": 1, "pcm_profiles": models}))
        service = root / "broker"
        service.write_bytes(b"service")
        return provider, service

    def test_relocates_both_profiles_and_preserves_spectral_entries(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, service = self.prepare_input(root)
            previous = root / "existing.json"
            previous.write_text(json.dumps({"version": 1, "profiles": {"8": {"flag": True}}}))
            dst = root / "installed"
            identities = stage.prepare(candidate, previous, service, dst, 2)
            self.assertTrue(all(stage.digest(dst / path) == sha for path, sha in identities.items()))
            catalog = json.loads((dst / "providers.json").read_text())
            self.assertEqual(catalog["profiles"], {"8": {"flag": True}})
            for model, row in catalog["pcm_profiles"].items():
                self.assertEqual(Path(row["model"]).parent, dst / f"model{model}")
                self.assertTrue(row["compact_close"])
            with self.assertRaises(FileExistsError):
                stage.prepare(candidate, previous, service, dst, 1)

    def test_rejects_tampered_artifact_and_publishes_nothing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, service = self.prepare_input(root)
            (root / "original8/provider.so").write_bytes(b"unexpected")
            dst = root / "installed"
            with self.assertRaisesRegex(ValueError, "Identity mismatch"):
                stage.prepare(candidate, None, service, dst, 2)
            self.assertFalse(dst.exists())

    def test_rejects_outside_manifest_paths(self):
        for value in ("", "..", "../model.onnx", "/tmp/model.onnx"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stage.relative_path(value)


if __name__ == "__main__":
    unittest.main()
