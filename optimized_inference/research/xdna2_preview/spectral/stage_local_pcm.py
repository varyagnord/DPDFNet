#!/usr/bin/env python3
"""Stage an already qualified PCM provider catalog for a user-scoped host."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest
import json
import os
from pathlib import Path, PurePosixPath
from shutil import copyfile
from tempfile import TemporaryDirectory


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Invalid manifest-relative path {value!r}")
    return Path(*path.parts)


def references(node):
    if isinstance(node, dict):
        if {"path", "sha256", "bytes"} <= node.keys():
            yield relative_path(node["path"]), (node["sha256"], node["bytes"])
        for child in node.values():
            yield from references(child)
    elif isinstance(node, list):
        for child in node:
            yield from references(child)


def checked_copy(source, target, expected, size=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(source, target)
    if digest(target) != expected or (size is not None and target.stat().st_size != size):
        raise ValueError(f"Identity mismatch after copying {source.name}")
    return expected


def write_json(path, document):
    with path.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def prepare(candidate, existing, service, output, workers):
    candidate = json.loads(candidate.read_text())
    existing = json.loads(existing.read_text()) if existing else {"version": 1, "profiles": {}}
    if candidate.get("version") != 1 or existing.get("version") != 1:
        raise ValueError("Unsupported provider catalog version")
    selected = candidate["pcm_profiles"]
    if set(selected) != {"2", "8"}:
        raise ValueError("Expected exactly model 2 and model 8")
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)

    jobs = {}
    profile_catalog = {}
    for model, entry in sorted(selected.items()):
        profile_home = Path(f"model{model}")
        originals = {key: Path(entry[key]).resolve(strict=True) for key in ("library", "manifest", "model")}
        manifest = json.loads(originals["manifest"].read_text())
        entries = {}
        for path, identity in references(manifest):
            if path in entries and entries[path] != identity:
                raise ValueError(f"Conflicting identities for {path}")
            entries[path] = identity
        if not entries or int(model) not in {row["model"] for row in manifest["models"]}:
            raise ValueError(f"Incomplete assets for model {model}")
        for relative, (expected, size) in entries.items():
            jobs[profile_home / relative] = (originals["manifest"].parent / relative, expected, size)
        model_relative = originals["model"].relative_to(originals["manifest"].parent)
        if entries[model_relative][0] != entry["model_sha256"]:
            raise ValueError(f"Catalog model identity differs for model {model}")
        profile = dict(entry)
        for key in ("library", "manifest"):
            path = profile_home / originals[key].name
            if path in jobs:
                raise ValueError(f"Catalog artifact collides with a manifest reference at {path}")
            jobs[path] = (originals[key], entry[f"{key}_sha256"], None)
            profile[key] = str(output / path)
        profile["model"] = str(output / profile_home / model_relative)
        profile_catalog[model] = profile
    service_path = Path("dpdfnet-xdna2-service")
    jobs[service_path] = (service, digest(service), None)

    with TemporaryDirectory(prefix=".stage-pcm-", dir=output.parent) as tmp:
        temporary = Path(tmp)
        staging = temporary / "release"
        staging.mkdir(mode=0o700)

        def copy_item(item):
            relative, (source, expected, size) = item
            return str(relative), checked_copy(source, staging / relative, expected, size)

        with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            identities = dict(pool.map(copy_item, sorted(jobs.items())))
        (staging / service_path).chmod(0o755)
        write_json(staging / "providers.json",
                   existing | {"version": 1, "pcm_profiles": profile_catalog})
        identities["providers.json"] = digest(staging / "providers.json")
        write_json(staging / "SHA256.json", identities)
        staging.rename(output)
    return identities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualified-catalog", type=Path, required=True)
    parser.add_argument("--existing-catalog", type=Path)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=len(os.sched_getaffinity(0)))
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    identities = prepare(args.qualified_catalog, args.existing_catalog, args.service,
                         args.output, args.workers)
    print(json.dumps({"directory": str(args.output.absolute()), "verified_files": len(identities)}))


if __name__ == "__main__":
    main()
