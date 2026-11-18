"""Bind eight-argument XRT images and reconstruct the retired snapshot field."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from types import FunctionType

import r334_snapshot_build_v1 as snapshots
from r176_checkpoint_common_v2 import P, ROOT, read, sha, verify
from r192_checkpoint_v1 import emit
from r222_build_v1 import spec
from r254_prepare_native_v1 import replace
from r326_checkpoint_v1 import same_results
from r331_native_build_v1 import compile_owner
from r337_native_binding_v1 import PCM_KIND as OLD_PCM_KIND, RESULT as PRIOR_NATIVE
from r339_static_v1 import OUTPUT as STATIC, SERIAL

sys.path.insert(0, str(ROOT / "optimized_inference/tools"))
from offline_parallel import runtime_report, worker_count

OUTPUT = P / "r339_five_argument_native_v1"
SNAPSHOTS = P / "r339_snapshot_owners_v1"
RESULT = OUTPUT / "BUILDS.json"
WITH_SNAPSHOTS = SNAPSHOTS / "BUILDS.json"
CONTRACT = P / "r339_native_contract_v1.h"
OLD_CONTRACT = P / "r331_native_contract_v1.h"
PCM_KIND = "dpdfnet-private-model2-five-data-arguments-pcm-v1"
NATIVE_KIND = "dpdfnet-private-model2-five-data-arguments-native-v1"
OLD_NATIVE_KIND = "dpdfnet-private-resident-three-command-precision-v1"
DATA_BYTES = 857856
DATA_BUFFERS = 7
REMOVED_BYTES = 4352


def contract_source():
    text = OLD_CONTRACT.read_text().replace("namespace r331", "namespace r339")
    return replace(text, "args.size() == 9, \"Expected six resident data arguments\"",
                   "args.size() == 8, \"Expected five resident data arguments\"").replace(
        OLD_NATIVE_KIND, NATIVE_KIND)


def joint_source(text, original_hash, current_hash):
    for old, new in (
        ("r331_native_contract_v1.h", CONTRACT.name),
        ("r331::Prepared", "r339::Prepared"),
        (original_hash, current_hash),
        ("+PACKED[4]", ""),
        ("static_assert(physical_bytes==862208)", f"static_assert(physical_bytes=={DATA_BYTES})"),
        ("gru_in=6, gru_out=7, total_buffers=8", f"gru_in=5, gru_out=6, total_buffers={DATA_BUFFERS}"),
        ('slot<7 && slot!=5,"DPRNN BO slot"', 'slot<7 && slot!=4 && slot!=5,"DPRNN BO slot"'),
        ("return slot==6?5:slot;", "return slot==6?4:slot;"),
        ("{0u,1u,2u,3u,4u,6u}", "{0u,1u,2u,3u,6u}"),
        ("allocate(guarded,5);", "allocate(guarded,4);"),
        ("slot=0;slot<6;++slot", "slot=0;slot<5;++slot"),
        ("slot==5?gru_out:slot", "slot==4?gru_out:slot"),
        ("      if (slot != 5) {", "      // Immutable normalization bytes come from the original host initializer.\n"
                                  "      if (slot != 4 && slot != 5) {"),
    ):
        count = 2 if old == "r331::Prepared" else 1
        text = replace(text, old, new, count)
    return text


def prepare(job):
    arm, stat, previous = job
    assert stat["passed"] and stat["PDI_and_CDO_unchanged"]
    start = previous["release"]
    assert start["physical_data_BOs"] == DATA_BUFFERS + 1
    assert start["physical_data_bytes"] == DATA_BYTES + REMOVED_BYTES
    verify(start["source_sha256"])
    manifest_path = Path(start["manifest"]["path"])
    assert spec(manifest_path) == start["manifest"]
    manifest = read(manifest_path)
    old_registry = manifest["candidate_binding"]
    assert spec(old_registry["path"]) == old_registry
    binding = read(old_registry["path"])
    assert binding["initializer"] == start["initializer"]
    assert spec(binding["initializer"]["path"]) == binding["initializer"]
    binding.update(kind=NATIVE_KIND, xclbin=stat["image"],
                   commands=[stat["commands"][name] for name in ("dprnn_dual2", "gru", "gru_dual")])
    tag = "r339_" + arm.replace("-", "_")
    registry = P / f"{tag.upper()}_NATIVE_V1.json"
    new_manifest = P / f"{tag.upper()}_PCM_V1.json"
    emit(registry, binding)
    emit(new_manifest, dict(manifest, kind=PCM_KIND, candidate_binding=spec(registry)))
    donor = tag.replace("r339_", "r337_", 1)
    for suffix in ("joint_v1.h", "backend_v1.h", "pcm_v1.cpp"):
        source = P / f"{donor}_{suffix}"
        assert sha(source) == start["source_sha256"][str(source)]
        text = source.read_text().replace(donor, tag).replace(OLD_PCM_KIND, PCM_KIND)
        if suffix == "joint_v1.h":
            text = joint_source(text, old_registry["sha256"], sha(registry))
        if suffix == "pcm_v1.cpp":
            text = replace(text, OLD_NATIVE_KIND, NATIVE_KIND)
        emit(P / f"{tag}_{suffix}", text)
    folder = OUTPUT / arm
    folder.mkdir()
    return dict(arm=arm, model=2, profile=manifest["profile"], root=str(folder), tag=tag, original=previous,
                old_manifest=str(manifest_path), native=str(registry), manifest=str(new_manifest),
                data_bytes=DATA_BYTES, initializer=binding["initializer"],
                legacy_weights_compared_bytes=start["legacy_weights_compared_bytes"])


def compile_native(task):
    arm, mode, result = compile_owner(task)
    # The shared cold runner predates seven-buffer owners and labels every release as eight.
    result["physical_data_BOs"] = DATA_BUFFERS
    result["source_sha256"][str(CONTRACT)] = sha(CONTRACT)
    return arm, mode, result


def compile_snapshot(task):
    arm, _, mode, result = snapshots.compile_variant(task)
    result["physical_data_BOs"] = DATA_BUFFERS
    result["source_sha256"][str(CONTRACT)] = sha(CONTRACT)
    return arm, mode, result


def by_profile(rows, jobs):
    return {arm: {mode: result for name, mode, result in rows if name == arm} for arm in jobs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be positive")
    reports = (STATIC, SERIAL, PRIOR_NATIVE)
    proof, serial, previous = map(read, reports)
    assert all(row["passed"] and row["actual_NPU_commands"] == 0 for row in (proof, serial, previous))
    assert same_results(proof, serial)
    verify(proof["evidence_sha256"] | previous["evidence_sha256"])
    names = list(proof["profiles"])
    assert len(names) == 3
    OUTPUT.mkdir()
    SNAPSHOTS.mkdir()
    emit(CONTRACT, contract_source())
    workers = worker_count(2 * len(names), args.workers)
    prepare_snapshot = FunctionType(snapshots.prepare.__code__, dict(snapshots.prepare.__globals__, OUTPUT=SNAPSHOTS))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        prepared = list(pool.map(prepare, [(arm, proof["profiles"][arm], previous["profiles"][arm]) for arm in names]))
        bound = list(pool.map(compile_native, [
            (item, mode, [other for other in prepared if other is not item])
            for item in prepared for mode in ("release", "asan")
        ]))
        profiles = by_profile(bound, names)
        for_snapshot = list(pool.map(prepare_snapshot, [(arm, "short", forms) for arm, forms in profiles.items()]))
        hooked = list(pool.map(compile_snapshot, [(item, mode) for item in for_snapshot for mode in ("release", "asan")]))
    assert sum(result["controls"] for _, _, result in bound) == 30 and len(hooked) == 6
    common = dict(passed=True, actual_NPU_commands=0, Python=runtime_report(workers),
                  source_sha256={str(path): sha(path) for path in (Path(__file__).resolve(), CONTRACT, OLD_CONTRACT)},
                  evidence_sha256={str(path): sha(path) for path in reports},
                  normalization_BO_bytes_removed=REMOVED_BYTES)
    emit(RESULT, dict(common, cold_controls=30, profiles=profiles))
    emit(WITH_SNAPSHOTS, dict(common, cold_controls=6, profiles=by_profile(hooked, names)))
    print("Verified thirty native and six diagnostic cold controls without opening XDNA2.", flush=True)


if __name__ == "__main__":
    main()
