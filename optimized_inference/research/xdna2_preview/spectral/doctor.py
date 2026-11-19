"""Report the local EasyEffects integration prerequisites without opening the NPU."""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import subprocess


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def hardware():
    return [str(path) for path in Path("/dev/accel").glob("accel[0-9]*")
            if path.is_char_device() and os.access(path, os.R_OK | os.W_OK)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--ladspa", type=Path)
    parser.add_argument("--flatpak", metavar="APP_ID")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    profiles = {}
    for model, profile in catalog["profiles"].items():
        cells = {}
        for name in ("library", "manifest"):
            path = Path(profile[name])
            cells[name] = path.is_file() and digest(path) == profile[f"{name}_sha256"]
        profiles[model] = {"files_valid": all(cells.values()),
                           "live_qualified": profile["qualified_for_live_audio"],
                           "auto_qualified": profile["auto_qualified"]}
    report = {"hardware": hardware(), "catalog_version": catalog["version"], "profiles": profiles}
    if args.ladspa:
        lib = c.CDLL(str(args.ladspa.resolve(strict=True)))
        report["ladspa"] = hasattr(lib, "ladspa_descriptor")
        report["optional_backend_abi"] = all(hasattr(lib, "hushmic_dpdfnet_" + op + "_xdna2_v1")
                                             for op in ("prepare", "policy", "set_policy", "status"))
    if args.flatpak:
        info = subprocess.run(["flatpak", "info", "--show-permissions", args.flatpak],
                              check=True, capture_output=True, text=True, timeout=10)
        report["flatpak_service_permission"] = "io.github.fovty.HushMic.XDNA2=talk" in info.stdout
        report["flatpak_all_devices_granted"] = any(
            line.startswith("devices=") and "all" in line.partition("=")[2].split(";")
            for line in info.stdout.splitlines())
    print(json.dumps(report, indent=2))
    raise SystemExit(not (report["hardware"] and catalog["version"] == 1 and profiles
                          and all(row["files_valid"] for row in profiles.values())
                          and report.get("optional_backend_abi", True)
                          and report.get("flatpak_service_permission", True)
                          and not report.get("flatpak_all_devices_granted", False)))


if __name__ == "__main__":
    main()
