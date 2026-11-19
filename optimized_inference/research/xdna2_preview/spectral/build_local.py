"""Build the two spectral providers against this host's verified WAV preview."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[2] / "examples/xdna2_preview.json"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def checked(root, entry):
    path = (root / entry["path"]).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
        raise ValueError(f"Changed preview artifact: {path}")
    return path


def build(root, out, model):
    catalog = read(CATALOG)["models"][str(model)]
    entry = catalog["profiles"][catalog["default"]]
    manifest = checked(root, entry["manifest"])
    original = checked(root, entry["model"])
    preview = checked(root, entry["library"])
    if model == 2:
        command = read(root / "r339_five_argument_native_v1/BUILDS.json")["profiles"][
            "m2-df-bfp16-k128"]["release"]["command"]
    else:
        command = read(root / "r306_persistent_request_padding_v1/RESULTS.json")["compile_commands"]["release"]

    output = out / f"libdpdfnet-xdna2-model{model}.so"
    source = HERE / "spectral.cpp"
    includes = [arg for arg in command if arg.startswith("-I")]
    includes.append(f"-I{root}")
    if model == 8:
        includes.insert(0, f"-I{root / 'r328_no_weight_BO_native_v1'}")
        includes.append(f"-I{root / 'r306_persistent_request_padding_v1'}")
    libraries = [arg for arg in command if "libxrt_coreutil.so" in arg or arg.endswith("/libonnxruntime.so")]
    runtime_paths = ":".join(str(Path(lib).parent) for lib in libraries)
    argv = [command[0], "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-ffp-contract=off",
            "-fno-fast-math", "-shared", "-fPIC", f"-DDPDFNET_XDNA2_MODEL={model}",
            *includes, f"-Wl,--version-script={HERE / 'spectral.map'}", str(source),
            *libraries, "-lcrypto", "-ldl", f"-Wl,-rpath,{runtime_paths}", "-o", str(output)]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LD_", "DPDF_")) and key not in ("BASH_ENV", "ENV")}
    with (out / f"model{model}.log").open("x") as log:
        subprocess.run(argv, env=env, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    return str(model), {
        "library": str(output), "library_sha256": digest(output),
        "manifest": str(manifest), "manifest_sha256": digest(manifest),
        "model_sha256": digest(original), "profile": catalog["default"], "source_sha256": digest(source),
        "wav_preview_sha256": digest(preview), "auto_qualified": False,
        "qualified_for_live_audio": False, "commands_per_frame": entry["commands_per_frame"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preview_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    root = args.preview_root.resolve(strict=True)
    out = args.output.resolve()
    out.mkdir(mode=0o700)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        profiles = dict(pool.map(lambda model: build(root, out, model), (2, 8)))
    (out / "providers.json").write_text(json.dumps({"version": 1, "profiles": profiles}, indent=2) + "\n")


if __name__ == "__main__":
    main()
