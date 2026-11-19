"""Prepare a separate EasyEffects .Devel manifest from local integration checkouts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def files(source, dest):
    paths = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    for raw in paths.rstrip(b"\0").split(b"\0"):
        file = Path(raw.decode())
        if file.is_absolute() or ".." in file.parts:
            raise ValueError(f"Unexpected source path: {file}")
        target = dest / file
        if (source / file).is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / file, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("easyeffects", "hushmic", "flathub", "assets", "stage"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve()
    stage.mkdir(mode=0o700)
    files(args.easyeffects, stage / "easyeffects")
    files(args.hushmic, stage / "hushmic")
    for name in ("models", "lib"):
        shutil.copytree(args.assets / name, stage / "assets" / name)

    fname = "com.github.wwmm.easyeffects"
    manifest = json.loads((args.flathub / f"{fname}.json").read_text())
    manifest["id"] = f"{fname}.Devel"
    manifest["sdk-extensions"] = ["org.freedesktop.Sdk.Extension.rust-stable"]
    manifest["finish-args"].append("--talk-name=io.github.fovty.HushMic.XDNA2")
    easy = manifest["modules"][0]
    easy["config-opts"].append("-DENABLE_DEVEL=ON")
    easy["sources"] = [{"type": "dir", "path": str(stage / "easyeffects")}]
    modules = json.loads((args.flathub / "easyeffects-modules.json").read_text())
    for dependency in modules["modules"]:
        for src in dependency.get("sources", ()):
            url = src.get("url", "")
            if dependency["name"] == "gsl" and url == "https://ftp.gnu.org/gnu/gsl/gsl-2.8.tar.gz":
                # Same archive and SHA-256 from a working GNU mirror.
                src["url"] = "https://www.mirrorservice.org/sites/ftp.gnu.org/gnu/gsl/gsl-2.8.tar.gz"
            if dependency["name"] == "rnnoise" and url.endswith("2e3c812c62c32b3ac486c3cd4f4894e6f57d45fd.zip"):
                src.clear()
                src.update(type="git", url="https://github.com/xiph/rnnoise.git",
                           commit="2e3c812c62c32b3ac486c3cd4f4894e6f57d45fd")
    # Keep patch paths anchored to the original manifest.
    for dependency in modules["modules"]:
        for src in dependency.get("sources", ()):
            if src["type"] in ("file", "patch") and "path" in src:
                src["path"] = str((args.flathub / src["path"]).resolve())
    module_file = stage / "easyeffects-modules.json"
    module_file.write_text(json.dumps(modules, indent=2) + "\n")
    easy["modules"] = [str(module_file)]
    manifest["modules"].insert(0, {
        "name": "hushmic-dpdfnet",
        "buildsystem": "simple",
        "build-options": {"append-path": "/usr/lib/sdk/rust-stable/bin", "env": {
            "HUSHMIC_BUILD_MODEL": "/app/share/dpdfnet/models/dpdfnet8_48khz_hr.onnx",
            "HUSHMIC_BUILD_DYLIB": "/app/lib/dpdfnet/libonnxruntime.so",
            "CARGO_NET_OFFLINE": "true",
        }},
        "sources": [
            {"type": "dir", "path": str(stage / "hushmic")},
            {"type": "dir", "path": str(stage / "cargo-vendor"), "dest": "vendor"},
            {"type": "dir", "path": str(stage / "assets"), "dest": "local-assets"},
        ],
        "build-commands": [
            "mkdir -p .cargo",
            "printf '[source.crates-io]\\nreplace-with = \"vendored-sources\"\\n"
            "[source.vendored-sources]\\ndirectory = \"vendor\"\\n' > .cargo/config.toml",
            "cargo build --locked --offline --release -p dpdfnet-ladspa --features xdna2",
            "install -Dm755 target/release/libdpdfnet_ladspa.so /app/lib/ladspa/libdpdfnet_ladspa.so",
            "install -Dm755 local-assets/lib/libonnxruntime.so /app/lib/dpdfnet/libonnxruntime.so",
            "install -d /app/share/dpdfnet/models",
            "install -m644 local-assets/models/* /app/share/dpdfnet/models/",
        ],
    })
    (stage / f"{fname}.Devel.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
