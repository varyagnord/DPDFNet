"""Prove that only the obsolete XRT argument and later slot numbers changed."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sys

from r176_checkpoint_common_v2 import P, ROOT, read, sha, verify
from r192_checkpoint_v1 import emit
from r222_build_v1 import spec
from r263_dual_dprnn_static_v1 import constants, controls, entries
from r308_static_v1 import core_logic
from r327_static_v1 import tx_ops
from r330_static_v1 import precision_descriptors, precision_memory
from r337_resident_norm_audit_v1 import OUTPUT as PRIOR_STATIC
from r339_build_v1 import BUILDS, PRIOR_BUILDS

sys.path.insert(0, str(ROOT / "optimized_inference/tools"))
from offline_parallel import runtime_report, worker_count

OUTPUT = P / "R339_FIVE_ARGUMENT_STATIC_V1.json"
SERIAL = P / "R339_FIVE_ARGUMENT_STATIC_SERIAL_V1.json"
MEMREF = re.compile(r'%arg\d+: (memref<[^>]+>)')
FIRMWARE_TRANSLATION = 0x80000000
OUTPUT_OFFSETS = {"erb2": [0], "df2": [0], "gru": [0], "gru_pair": [0],
                  "gru_dual": [0, 2560], "dprnn_dual2": [0, 12416]}


def move_output_patch(op):
    if op[0] != 129 or op[8] != 5:
        return op
    # Firmware translates the first five arguments; the compiler compensates
    # in the old sixth argument's offset. Physical offsets stay identical.
    assert len(op) == 12 and op[9] == op[11] == 0 and op[10] >= FIRMWARE_TRANSLATION
    return op[:8] + (4, op[9], op[10] - FIRMWARE_TRANSLATION, op[11])


def inspect(job):
    arm, candidate, original, proof = job
    assert all(item["passed"] for item in (candidate, original, proof))
    assert all(item["no_accelerator_open"] for item in (candidate, original))
    receipts = [Path(item["compile"]["path"]) for item in (original, candidate)]
    assert all(spec(path) == item["compile"] for path, item in zip(receipts, (original, candidate), strict=True))
    old, new = map(read, receipts)
    paths = [Path(record["physical"]["path"]) for record in (old, new)]
    assert all(spec(path) == record["physical"] for path, record in zip(paths, (old, new), strict=True))
    old_entries, new_entries = [entries(path, 6) for path in paths]
    assert old_entries.keys() == new_entries.keys()
    evidence = {str(path): sha(path) for path in (*paths, *receipts)}
    result = {}
    for name, after in new_entries.items():
        before = old_entries[name]
        arguments = [MEMREF.findall(text.splitlines()[0]) for text in (before, after)]
        assert len(arguments[0]) == 6 and arguments[0][4] == "memref<1088xf32>"
        assert arguments[1] == arguments[0][:4] + arguments[0][5:]
        assert controls(before, constants(before)) == controls(after, constants(after))
        descriptors = precision_descriptors(before)
        assert all(row["slot"] != 4 for row in descriptors)
        assert precision_descriptors(after) == [
            dict(row, slot=4) if row["slot"] == 5 else row for row in descriptors
        ]
        source, target = [Path(record["commands"][name]["path"]) for record in (old, new)]
        assert spec(source) == old["commands"][name] == proof["commands"][name]
        assert spec(target) == new["commands"][name]
        assert source.stat().st_size == target.stat().st_size
        initial, final = [list(tx_ops(path)) for path in (source, target)]
        remapped = [op for op in initial if op[0] == 129 and op[8] == 5]
        assert not any(op[0] == 129 and op[8] == 4 for op in initial)
        assert [op[10] - FIRMWARE_TRANSLATION for op in remapped] == OUTPUT_OFFSETS[name]
        assert final == list(map(move_output_patch, initial))
        evidence.update({str(path): sha(path) for path in (source, target)})
        result[name] = dict(argument_count=5, relocated_patches=len(remapped), instruction_bytes=target.stat().st_size,
                            ordered_DDR_descriptors=len(descriptors), exact_output_offsets=OUTPUT_OFFSETS[name])
    assert core_logic(paths[0].read_text()) == core_logic(paths[1].read_text())
    assert precision_memory(paths[0], ()) == precision_memory(paths[1], ())
    old_image, new_image = [Path(record["xclbin"]["path"]) for record in (old, new)]
    assert spec(old_image) == old["xclbin"] == proof["image"] and spec(new_image) == new["xclbin"]
    evidence.update({str(path): sha(path) for path in (old_image, new_image)})
    for asset in ("main.pdi", "cdo_main/main_aie_cdo_init.bin"):
        first, second = (path.parent / asset for path in (old_image, new_image))
        assert first.read_bytes() == second.read_bytes(), (arm, asset)
        evidence.update({str(path): sha(path) for path in (first, second)})
    device_image = (new_image.parent / "main.pdi").read_bytes()
    assert new_image.read_bytes().count(device_image) == 1
    return arm, dict(passed=True, image=spec(new_image), commands=new["commands"], entries=result,
                     PDI_and_CDO_unchanged=True, obsolete_DDR_argument_removed=True,
                     evidence_sha256=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be positive")
    inputs = (BUILDS, PRIOR_BUILDS, PRIOR_STATIC)
    current, previous, prior_proof = map(read, inputs)
    assert all(row["passed"] and row["actual_NPU_commands"] == 0 for row in (current, previous, prior_proof))
    verify(current["source_sha256"] | prior_proof["evidence_sha256"])
    work = [(arm, row, previous["profiles"][arm], prior_proof["profiles"][arm])
            for arm, row in current["profiles"].items()]
    count = worker_count(len(work), args.workers)
    if count == 1:
        profiles = dict(map(inspect, work))
    else:
        with ThreadPoolExecutor(max_workers=count) as pool:
            profiles = dict(pool.map(inspect, work))
    evidence = {str(path): sha(path) for path in inputs}
    for row in profiles.values():
        evidence.update(row["evidence_sha256"])
    emit(args.output, dict(passed=True, profiles=profiles, actual_NPU_commands=0, Python=runtime_report(count),
                           source_sha256={__file__: sha(__file__)}, evidence_sha256=evidence))
    print(f"Verified all six command entries in {len(profiles)} images.", flush=True)


if __name__ == "__main__":
    main()
