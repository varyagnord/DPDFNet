"""Recompile the resident-norm graphs with five physical data arguments."""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import importlib
import os
from pathlib import Path
import re
import sys

from r176_checkpoint_common_v2 import P, ROOT, read, sha, verify
from r192_checkpoint_v1 import emit
from r222_build_v1 import execute, spec
from r222_sdk_env_v1 import PEANO, VENV
from r254_prepare_native_v1 import replace
from r333_build_v1 import ENTRIES, TRACER, environment
from r337_resident_norm_build_v1 import BUILDS as PRIOR_BUILDS

sys.path.insert(0, str(ROOT / "optimized_inference/tools"))
from offline_parallel import runtime_report, worker_count

HERE = Path(__file__).resolve()
OUTPUT = P / "r339_five_argument_aot_v1"
BUILDS = OUTPUT / "BUILDS.json"
PARENT = P / "PROGRESS_338_PROVENANCE.json"
SEGMENTS = P / "r339_resident_segments_v1.py"


def graph_source(original):
    for old, new in (
        (",norm_weights:In", ""),
        ("r331_resident_segments_v1", SEGMENTS.stem),
        (", 4: 544", ""),
        ("a,h,iw,tw,nw,out", "a,h,iw,tw,out"),
        (" snw=np.ndarray[(2*BANK_LANE[4],),np.dtype[np.float32]]\n", ""),
        ("types=[ct,sh,sw,stw,snw,ct,", "types=[ct,sh,sw,stw,ct,"),
        ("signature=[ct,sh,sw,stw,snw,ct]", "signature=[ct,sh,sw,stw,ct]"),
    ):
        original = replace(original, old, new)
    return original


def compile_image(folder):
    import numpy as np
    from aie.iron.device import from_name
    from aie.utils import set_current_device
    from aie.utils.config import peano_cxx_path
    from ml_dtypes import bfloat16

    frozen = read(folder / "FROZEN.json")
    verify(frozen["files"])
    assert Path(peano_cxx_path()).resolve() == PEANO / "bin/clang++"
    cache = folder / "cache"
    assert Path(os.environ["NPU_CACHE_HOME"]) == cache
    cache.mkdir()
    set_current_device(from_name("npu2", n_cols=8))
    graph = importlib.import_module(Path(frozen["graph"]).stem).joint_dual_dprnn
    types = {"0": np.float32, "1": np.float32, "2": bfloat16, "3": np.uint16, "6": np.float32}
    assert frozen["lanes"].keys() == types.keys()
    banks = {slot: np.ndarray[(2 * words,), np.dtype[types[slot]]]
             for slot, words in frozen["lanes"].items()}
    design = graph.specialize(x=banks["0"], state=banks["1"], intra_weights=banks["2"],
                              tail_weights=banks["3"], y=banks["6"])
    image, = (Path(path) for path in design.compile() if Path(path).suffix == ".xclbin")
    commands = {entry: spec(design.compilable.entry_insts_path("main:" + entry)) for entry in ENTRIES}
    assert image.is_relative_to(cache) and len(commands) == 6
    emit(folder / "COMPILE.json", dict(passed=True, model=2, arm=frozen["arm"], commands=commands,
         physical=spec(image.parent / "input_with_addresses.mlir"), xclbin=spec(image), actual_NPU_commands=0))


def build_images(workers_limit):
    assert sha(PARENT) == read(P / "R338_POSTSEAL_READBACK_V1.json")["manifest_sha256"]
    parent, previous = map(read, (PARENT, PRIOR_BUILDS))
    assert previous["passed"] and previous["actual_NPU_commands"] == 0
    verify(previous["source_sha256"])
    old_helper = P / "r331_resident_segments_v1.py"
    emit(SEGMENTS, replace(old_helper.read_text(), "_intra, _tail, _norm, y,",
                           "_intra, _tail, y,"))
    common = {str(path): sha(path) for path in (HERE, PARENT, PRIOR_BUILDS, old_helper, SEGMENTS)}
    OUTPUT.mkdir()
    workers = worker_count(len(previous["profiles"]), workers_limit)
    inner_jobs = max(1, worker_count(32) // workers)

    def build(job):
        arm, original = job
        assert original["passed"] and original["no_accelerator_open"]
        for key in ("freeze", "new_graph", "compile"):
            assert original[key] == spec(original[key]["path"])
        source = Path(original["new_graph"]["path"])
        prior = read(original["freeze"]["path"])
        verify(prior["files"])
        target = P / f'r339_{arm.replace("-", "_")}_graph_v1.py'
        body = graph_source(source.read_text())
        ast.parse(body, filename=str(target))
        emit(target, body)
        folder = OUTPUT / arm
        folder.mkdir()
        files = prior["files"] | common | {str(target): sha(target)}
        frozen = folder / "FROZEN.json"
        emit(frozen, dict(files=files, arm=arm, graph=str(target),
                          lanes={slot: extent for slot, extent in prior["lanes"].items() if slot != "4"}))
        env = environment(folder / "cache")
        env.update(R277_MODEL="2", AIE_KERNEL_COMPILE_JOBS=str(inner_jobs))
        trace, log = folder / "aot.strace", folder / "aot.log"
        cmd = [str(TRACER), "-f", "-qq", "-s", "384", "-e", "trace=openat,openat2,ioctl", "-o", str(trace),
               str(VENV / "bin/python"), "-B", str(HERE), "--compile", str(folder)]
        try:
            execute(cmd, log, env, 900)
        finally:
            assert not re.search(r'"/dev/(?:accel|dri|xdna|xclmgmt)', trace.read_text())
        result = folder / "COMPILE.json"
        assert read(result)["passed"]
        verify(files)
        return arm, dict(passed=True, compile=spec(result), freeze=spec(frozen), trace=spec(trace),
                         log=spec(log), graph=spec(target), no_accelerator_open=True)

    jobs = list(previous["profiles"].items())
    if workers == 1:
        profiles = dict(map(build, jobs))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            profiles = dict(pool.map(build, jobs))
    verify(parent["reference_worktree_frozen_files_sha256"])
    emit(BUILDS, dict(passed=True, profiles=profiles, actual_NPU_commands=0,
                      source_sha256=common, Python=runtime_report(workers)))
    print(f"Linked {len(profiles)} images with five data arguments.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", type=Path)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be positive")
    if args.compile:
        compile_image(args.compile)
    else:
        build_images(args.workers)


if __name__ == "__main__":
    main()
