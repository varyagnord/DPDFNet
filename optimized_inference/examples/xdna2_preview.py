"""Opt-in Linux XDNA2 WAV preview for the qualified local runtime."""

import ctypes as C
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic


CATALOG = Path(__file__).with_name("xdna2_preview.json")
XRT = Path("/opt/xilinx/xrt")
PCM_WORDS = 480
PCM_BYTES = PCM_WORDS * 4
MAX_HOPS = 1048576


def verified(root, entry):
    path = (root / entry["path"]).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != entry["bytes"]:
        raise ValueError(f"Unexpected preview file: {entry['path']}")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
            raise ValueError(f"Preview file changed: {entry['path']}")
    return path


def bindings(root, model, profile):
    catalog = json.loads(CATALOG.read_text())
    identities = catalog["models"][str(model)]
    selected = profile or identities["default"]
    if selected not in identities["profiles"]:
        options = ", ".join(identities["profiles"])
        raise ValueError(f"Model {model} supports these XDNA2 preview profiles: {options}")
    row = identities["profiles"][selected]
    assets = {key: verified(root, row[key]) for key in ("library", "manifest", "model")}
    assets["owner"] = verified(root, catalog["owner"])
    return selected, assets, row["commands_per_frame"]


def contexts(folder, name):
    report = folder / f"{name}.json"
    subprocess.run([XRT / "bin/xrt-smi", "examine", "-r", "aie-partitions", "-f", "JSON", "-o", report],
                   check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    result = []
    def collect(value):
        if isinstance(value, dict):
            if "context_id" in value:
                result.append(value)
            else:
                for row in value.values():
                    collect(row)
        elif isinstance(value, list):
            for row in value:
                collect(row)
    collect(json.loads(report.read_text()))
    return result


def function(library, name, result, *args):
    fn = getattr(library, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


def worker(argv):
    path, manifest, model_path, folder, incoming, outgoing = map(Path, argv)
    model = int(model_path.name.removeprefix("dpdfnet").split("_", 1)[0])
    env_output = folder / "native"
    env_output.mkdir(mode=0o700)
    os.environ["DPDF_R103_OUTPUT_DIRECTORY"] = str(env_output)
    lib = C.CDLL(str(path))
    abi = function(lib, "r103_abi_version_v1", C.c_uint32)
    validate = function(lib, "r103_config_only_v1", C.c_int, C.c_char_p, C.c_int)
    create = function(lib, "audio_native_create", C.c_void_p, C.c_char_p, C.c_char_p)
    step = function(lib, "audio_native_step", C.c_int, C.c_void_p, C.c_void_p, C.c_void_p)
    finish = function(lib, "r103_finish_v1", C.c_int, C.c_void_p)
    destroy = function(lib, "r103_destroy_v1", C.c_int, C.c_void_p)
    if abi() != 1 or validate(os.fsencode(manifest), model) != 0:
        raise RuntimeError("XDNA2 model or native ABI validation failed")
    handle = create(os.fsencode(manifest), os.fsencode(model_path))
    if not handle:
        raise RuntimeError("XDNA2 could not open the selected model")
    try:
        before = contexts(folder, "opened")
        if len(before) != 1 or int(before[0]["pid"]) != os.getpid():
            raise RuntimeError("Expected one context owned by this worker")
        audio = (C.c_float * PCM_WORDS)()
        n = 0
        start = monotonic()
        with incoming.open("rb") as source, outgoing.open("xb") as target:
            for block in iter(lambda: source.read(PCM_BYTES), b""):
                if len(block) != PCM_BYTES or step(handle, block, audio) != 0:
                    raise RuntimeError("XDNA2 audio callback failed")
                target.write(audio)
                n += 1
        elapsed = monotonic() - start
        after = contexts(folder, "processed")
        if len(after) != 1 or any(after[0][key] != before[0][key] for key in ("pid", "context_id")):
            raise RuntimeError("XDNA2 context changed while processing")
        deltas = {key: int(after[0][key]) - int(before[0][key]) for key in
                  ("command_submissions", "command_completions", "errors")}
        if deltas["errors"] or deltas["command_submissions"] != deltas["command_completions"]:
            raise RuntimeError("XDNA2 command accounting failed")
        if finish(handle) != 0:
            raise RuntimeError("XDNA2 finish failed")
    finally:
        if destroy(handle) != 0:
            raise RuntimeError("XDNA2 native destruction failed")
    if contexts(folder, "closed"):
        raise RuntimeError("XDNA2 context remained after native close")
    print(json.dumps(dict(frames=n, processing_seconds=elapsed, **deltas)), flush=True)


def enhance(audio, root, model, profile):
    import numpy as np

    root = root.resolve(strict=True)
    selected, assets, commands = bindings(root, model, profile)
    # Match the qualified PCM corpus's six drain hops and 2,400-sample alignment.
    hops = (audio.size + PCM_WORDS - 1) // PCM_WORDS + 6
    if audio.size == 0 or hops > MAX_HOPS:
        raise ValueError("Unsupported XDNA2 WAV length")
    xrt = XRT / "bin/xrt-smi"
    if not xrt.is_file() or not any(Path("/dev/accel").glob("accel[0-9]*")):
        raise RuntimeError("XRT or the host accelerator device is unavailable")
    with (root / "xdna2-preview.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix="xdna2-preview-", dir=root) as temporary:
            folder = Path(temporary)
            if contexts(folder, "idle"):
                raise RuntimeError("XDNA2 already has an active context")
            incoming, outgoing = folder / "input.f32", folder / "output.f32"
            np.pad(audio.astype("<f4", copy=False), (0, hops * PCM_WORDS - audio.size)).tofile(incoming)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("DPDF_", "LD_")) and key not in ("BASH_ENV", "ENV")}
            env.update(LD_PRELOAD="/usr/lib64/libstdc++.so.6", LD_LIBRARY_PATH=str(XRT / "lib"),
                       XILINX_XRT=str(XRT), OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            argv = [assets["owner"], str(os.getpid()), "/usr/bin/python3", "-I", "-B",
                    Path(__file__).resolve(), "_worker", assets["library"], assets["manifest"],
                    assets["model"], folder, incoming, outgoing]
            try:
                result = subprocess.run(argv, timeout=45 + hops * 0.02,
                                        capture_output=True, text=True, env=env)
            finally:
                if contexts(folder, "reaped"):
                    raise RuntimeError("XDNA2 still reports a context after worker reap")
            if result.returncode:
                detail = result.stderr.strip().splitlines()
                raise RuntimeError(f"XDNA2 worker exited with status {result.returncode}: "
                                   f"{detail[-1] if detail else 'no diagnostic returned'}")
            report = json.loads(result.stdout)
            if report["frames"] != hops or report["command_completions"] != commands * hops:
                raise RuntimeError("Unexpected XDNA2 frame or command count")
            pcm = np.fromfile(outgoing, dtype="<f4")
            if pcm.size != hops * PCM_WORDS or not np.isfinite(pcm).all():
                raise RuntimeError("XDNA2 returned invalid PCM")
    print(json.dumps(dict(backend="xdna2", model=model, profile=selected, **report)), file=sys.stderr)
    return pcm[2400:2400 + audio.size]


if __name__ == "__main__":
    if len(sys.argv) != 8 or sys.argv[1] != "_worker":
        raise SystemExit("Run enhance_wav.py with --backend xdna2")
    worker(sys.argv[2:])
