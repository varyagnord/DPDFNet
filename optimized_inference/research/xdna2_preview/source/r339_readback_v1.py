"""Verify all native state bytes and reconcile the retired buffer's API traffic."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from inspect import getsource
from pathlib import Path
import sys

import r334_readback_v1 as reader
from r176_checkpoint_common_v2 import P, ROOT, read, sha, verify
from r192_checkpoint_v1 import emit
from r254_prepare_native_v1 import replace
from r339_registration_v1 import ARMS, DATA_BUFFERS, DATA_BYTES, N, REFERENCE, ROOT_RUN, TOTAL, TOTAL_FRAMES, WITNESS, cases

sys.path.insert(0, str(ROOT / "optimized_inference/tools"))
from offline_parallel import runtime_report, worker_count

RESULT = ROOT_RUN / "R339_HARD_ROOT_RESULT_V1.json"
AUDIT = P / "R339_CURRENT_AUDIT_V1.json"
SCOPE = P / "R339_SCOPE_RESTORATION_V1.json"
TERMINAL = P / "R339_LAUNCH_TERMINAL_V1.json"
OLD_READER = P / "PROGRESS_334_PROVENANCE.json"
RETIRED_BYTES = 4352


def exact_reader():
    original = Path(reader.__file__).resolve()
    assert sha(original) == read(OLD_READER)["source_sha256"][original.name]
    # The logical endpoint is identical. Only the expectations for aligned
    # physical allocations and the number of snapshot sync calls differ.
    text = getsource(reader.inspect)
    for old, new in (('joint["physical_data_BOs"] == 8', f'joint["physical_data_BOs"] == {DATA_BUFFERS}'),
                     ("else 862208)", f"else {DATA_BYTES})"),
                     ("calls=12*count,", "calls=10*count,")):
        text = replace(text, old, new)
    module = dict(reader.inspect.__globals__, ROOT_RUN=ROOT_RUN)
    exec(compile(text, str(original), "exec"), module)
    return module["inspect"]


def inspect(task):
    job, indexed, witness, control, check = task
    assert dict(job, form=control["job"]["form"]) == control["job"]
    row = check((job, indexed, witness))
    row["NN_final"] = list(row["NN_final"])
    for field in ("pcm", "CPU", "reset_CPU", "NN_final", "NN_trajectory", "commands"):
        assert row[field] == control[field], (job["capture_id"], field)
    assert control["data_bytes"] - row["data_bytes"] == RETIRED_BYTES
    earlier, current = control["ledger"], row["ledger"]
    assert earlier.keys() == current.keys()
    reads = len(row["NN_trajectory"]) + 1 if job["diagnostic"] else 1
    expected = {"initial_staging": (2, RETIRED_BYTES), "initial_upload": (1, RETIRED_BYTES),
                "cold_download": (2 * reads, RETIRED_BYTES * reads)}
    assert {key: value for key, value in current.items() if key not in expected} == {
        key: value for key, value in earlier.items() if key not in expected
    }
    for key, (calls, requested_bytes) in expected.items():
        value = earlier[key]
        assert current[key] == dict(calls=value["calls"] - calls,
                                    requested_bytes=value["requested_bytes"] - requested_bytes), (job["capture_id"], key)
    row["startup_bytes_removed"] = RETIRED_BYTES
    row["bytes_removed_per_diagnostic_NN_readback"] = RETIRED_BYTES
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be positive")
    inputs = (RESULT, AUDIT, SCOPE, TERMINAL, WITNESS, REFERENCE)
    root, audit, scope, terminal, witness, prior = map(read, inputs)
    assert all(row["passed"] for row in (root, audit, scope, witness, prior))
    assert all(audit[key] for key in ("restored_exact", "fresh_context0", "fresh_default_NPU"))
    assert terminal["returncode"] == scope["returncode"] == 0 and terminal["subprocess_reaped"]
    assert scope["restored"] == scope["original"] and scope["kernel_after"] == scope["kernel_before"]
    assert scope["affinity"] == list(range(24))
    assert root["ownership"]["direct_child_reaped"] and not root["ownership"]["owned_remaining"]
    assert root["actual_total_device_commands"] == audit["known_commands"] == TOTAL
    verify(audit["evidence_sha256"] | root["protected_archive_sha256"] | scope["evidence_sha256"] |
           prior["evidence_sha256"])
    gold = {(row["job"]["arm"], row["job"]["source_index"]): row for row in witness["rows"]}
    controls = {row["job"]["capture_id"]: row for row in prior["results"]}
    native_reader = exact_reader()
    tasks = [(job, evidence, gold[job["image_profile"], job["source_index"]], controls[job["capture_id"]], native_reader)
             for job, evidence in zip(cases(), root["inner_result"]["cases"], strict=True)]
    count = worker_count(len(tasks), args.workers)
    if count == 1:
        rows = list(map(inspect, tasks))
    else:
        with ThreadPoolExecutor(max_workers=count) as pool:
            rows = list(pool.map(inspect, tasks))
    assert len(rows) == N and sum(row["commands"] for row in rows) == TOTAL
    assert sum(row["job"]["expected_frames"] for row in rows) == TOTAL_FRAMES
    states = sum(len(row["NN_trajectory"] or ()) for row in rows)
    assert states == 684
    evidence = {str(path): sha(path) for path in (*inputs, OLD_READER)}
    for row in rows:
        evidence.update(row.pop("evidence_sha256"))
    emit(args.output, dict(passed=True, owners=N, release_owners=len(ARMS), exact_PCM_frames=TOTAL_FRAMES,
                          exact_CPU_snapshots=TOTAL_FRAMES, exact_NN_trajectory_snapshots=states,
                          actual_device_commands=TOTAL, physical_data_BOs=DATA_BUFFERS, physical_data_bytes=DATA_BYTES,
                          retired_buffer_requested_bytes=RETIRED_BYTES, primary_timing_samples=0, results=rows,
                          Python=runtime_report(count), source_sha256={__file__: sha(__file__)}, evidence_sha256=evidence))
    print(f"Verified {N} seven-buffer owners and {states} full NN snapshots over {TOTAL} commands.", flush=True)


if __name__ == "__main__":
    main()
