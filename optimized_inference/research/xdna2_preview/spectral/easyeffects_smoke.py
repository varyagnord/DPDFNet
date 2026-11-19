"""Launch a synthetic, separate PipeWire graph and exercise native EasyEffects."""
import argparse
import contextlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time


BUS = ("busctl", "--user", "call", "io.github.fovty.HushMic.XDNA2",
       "/io/github/fovty/HushMic/XDNA2", "io.github.fovty.HushMic.XDNA2.V1")
XRT = "/opt/xilinx/xrt/bin/xrt-smi"


def command(args, env):
    return subprocess.check_output(args, env=env, stderr=subprocess.STDOUT, text=True, timeout=12)


def eventually(probe, timeout):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = probe()
            if last:
                return last
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Probe did not succeed: {last!r}")


class Processes:
    def __init__(self, directory, env):
        self.directory = directory
        self.env = env
        self.children = contextlib.ExitStack()

    def __enter__(self):
        self.children.__enter__()
        return self

    def __exit__(self, *error):
        return self.children.__exit__(*error)

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)

    def start(self, name, *args, env=None):
        log = self.children.enter_context((self.directory / f"{name}.log").open("xb"))
        p = subprocess.Popen(args, env=env or self.env, stdout=log, stderr=subprocess.STDOUT)
        self.children.callback(self.stop, p)
        return p


def preset(directory, mono, tag, direction):
    name = f"{tag} mono" if mono else f"{tag} stereo"
    section = {"plugins_order": ["deepfilternet#0"], "blocklist": [],
               "deepfilternet#0": {"model": "DPDFNet", "mono-processing": mono,
                                  "attenuation-limit": 65, "bypass": False,
                                  "output-gain": 0, "input-gain": 0}}
    (directory / f"{name}.json").write_text(json.dumps({direction: section}))
    return name


def contexts(env):
    return command([XRT, "examine", "-r", "aie-partitions"], env)



def owned_device(report, parent):
    rows = re.findall(r"^\s*\|(\d+)\s*\|(\d+)\s*\|(\d+)\s*\|.*?\|(\d+)\s*\|\s*N/A", report, re.M)
    counts = re.findall(r"\|Active\s*\|\s*(\d+)\s*\|", report)
    assert len(rows) == len(counts) == 1, report
    pid, context, submitted, errors = map(int, rows[0])
    with Path(f"/proc/{pid}/stat").open() as stream:
        stat = stream.read().split(") ", 1)[1].split()
    assert int(stat[1]) == parent
    completed = int(counts[0])
    assert errors == 0 and 0 <= submitted - completed <= 1
    return pid, context, int(stat[19]), completed


def set_preset(runtime, direction, name):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(runtime / "EasyEffectsServer"))
        client.sendall(f"load_preset:{direction}:{name}\n".encode())


def playback(procs, label, direction, input_path, env):
    if direction == "output":
        return procs.start(label, "pw-play", "--target", "easyeffects_sink", input_path)
    player = procs.start(label, "pw-play", "--target", "0", input_path)
    ports = eventually(lambda: [line for line in command(["pw-link", "-o"], env).splitlines()
                                if line.startswith("pw-play:output_")], 5)
    if len(ports) == 1:
        sources = ports * 2
    else:
        sources = ["pw-play:output_FL", "pw-play:output_FR"]
        assert all(port in ports for port in sources), ports
    for source, channel in zip(sources, ("FL", "FR"), strict=True):
        command(["pw-link", source, f"dpdfnet_test_source:input_{channel}"], env)
    return player


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--app", type=Path)
    mode.add_argument("--flatpak")
    p.add_argument("--fault-service-exit", action="store_true")
    p.add_argument("--only-mono", action="store_true")
    p.add_argument("--direction", choices=("input", "output"), default="output")
    p.add_argument("--rate", choices=(44100, 48000), type=int, default=48000)
    p.add_argument("--quantum", choices=(256, 480, 512, 1024), type=int, default=480)
    p.add_argument("--service", required=True, type=Path)
    p.add_argument("--providers", required=True, type=Path)
    p.add_argument("--ladspa", type=Path)
    p.add_argument("--model", required=True, type=Path)
    p.add_argument("--ort", type=Path)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--private", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if not args.private:
        import sys
        os.execvp("dbus-run-session", ["dbus-run-session", "--", sys.executable, "-B", *sys.argv, "--private"])
    if args.app and not (args.ladspa and args.ort):
        p.error("the native build requires --ladspa and --ort")
    if args.flatpak and args.flatpak != "com.github.wwmm.easyeffects.Devel":
        p.error("the Flatpak test requires the separate .Devel application")
    import numpy as np
    import soundfile as sf
    input_path = args.input.resolve(strict=True)
    length = sf.info(input_path).duration
    output = args.output.resolve()
    output.mkdir(mode=0o700)
    parent_runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    with tempfile.TemporaryDirectory(prefix="dpdfnet-", dir=parent_runtime if args.flatpak else None) as tmp:
        runtime = Path(tmp)
        env = dict(os.environ, XDG_RUNTIME_DIR=str(parent_runtime) if args.flatpak else tmp,
                   PIPEWIRE_RUNTIME_DIR=tmp, PIPEWIRE_REMOTE="pipewire-0",
                   XDG_CONFIG_HOME=str(output / "config"), XDG_DATA_HOME=str(output / "data"),
                   XDG_CACHE_HOME=str(runtime / "cache"), XDG_STATE_HOME=str(runtime / "state"),
                   HUSHMIC_XDNA2_PROVIDERS=str(args.providers.resolve(strict=True)),
                   HUSHMIC_XDNA2_DEVELOPMENT="1", QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
        if args.app:
            env.update(LADSPA_PATH=str(args.ladspa.resolve(strict=True).parent),
                       HUSHMIC_MODEL_PATH=str(args.model.resolve(strict=True)),
                       ORT_DYLIB_PATH=str(args.ort.resolve(strict=True)))
        tier = "quality" if args.model.name.startswith("dpdfnet8") else "light"
        env["HUSHMIC_DSP_TIER"] = tier
        assert "No hardware contexts" in contexts(env)
        with Processes(output, env) as procs:
            broker = procs.start("broker", args.service.resolve(strict=True))
            eventually(lambda: command([*BUS, "GetPolicy"], env), 4)
            command([*BUS, "SetPolicy", "y", "2"], env)
            procs.start("pipewire", shutil.which("pipewire"))
            eventually(lambda: (runtime / "pipewire-0").is_socket(), 5)
            procs.start("wireplumber", shutil.which("wireplumber"), "--profile=policy")
            command(["pw-cli", "create-node", "adapter",
                     "{ factory.name=support.null-audio-sink node.name=dpdfnet_test_sink"
                     " media.class=Audio/Sink object.linger=true audio.position=[ FL FR ] }"], env)
            command(["pw-cli", "create-node", "adapter",
                     "{ factory.name=support.null-audio-sink node.name=dpdfnet_test_source"
                     " media.class=Audio/Source/Virtual object.linger=true audio.position=[ FL FR ] }"], env)
            command(["pw-metadata", "-n", "settings", "0", "clock.force-rate", str(args.rate)], env)
            command(["pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(args.quantum)], env)
            if args.flatpak:
                socket_dir = runtime / "ee"
                socket_dir.mkdir(mode=0o700)
                app = ["flatpak", "run", "--user", "--no-documents-portal",
                       "--nofilesystem=xdg-run/pipewire-0", f"--filesystem=xdg-run/{runtime.name}:rw",
                       f"--env=PIPEWIRE_RUNTIME_DIR={runtime}",
                       f"--env=TMPDIR={socket_dir}",
                       "--env=QT_QPA_PLATFORM=offscreen", "--env=QT_QUICK_BACKEND=software",
                       "--env=PIPEWIRE_REMOTE=pipewire-0", f"--env=HUSHMIC_DSP_TIER={tier}",
                       f"--env=HUSHMIC_MODEL_PATH=/app/share/dpdfnet/models/{args.model.name}", args.flatpak]
            else:
                socket_dir = runtime
                app = [str(args.app.resolve(strict=True))]
            procs.start("easy", *app, "--hide-window", "--service-mode", "--debug")
            if args.flatpak:
                output_dir = Path.home() / ".var/app" / args.flatpak / "data/easyeffects" / args.direction
                eventually(output_dir.is_dir, 10)
            else:
                output_dir = eventually(lambda: next(iter((output / "data").glob(f"**/easyeffects/{args.direction}")), None), 10)
            tag = "DPDFNet test " + runtime.name
            mono = preset(output_dir, True, tag, args.direction)
            stereo = preset(output_dir, False, tag, args.direction)
            for name in (mono, stereo):
                procs.children.callback((output_dir / f"{name}.json").unlink, missing_ok=True)
            eventually(lambda: "easyeffects_sink" in command(["pw-link", "-i"], env), 10)
            (output / "ports-before.txt").write_text(command(["pw-link", "-iol"], env))
            eventually(lambda: (socket_dir / "EasyEffectsServer").is_socket(), 5)
            set_preset(socket_dir, args.direction, mono)
            picked = eventually(lambda: value if mono in
                                (value := command([*app, "--last-loaded-presets"], env)) else None, 5)
            (output / "preset-picked.txt").write_text(picked)
            capture = ["--target", "easyeffects_source"] if args.direction == "input" else [
                "--target", "dpdfnet_test_sink", "--properties", "stream.capture.sink=true"]
            recording = procs.start("record-mono", "pw-record", *capture, "--format", "f32",
                                    "--rate", str(args.rate), output / "mono.wav")
            play = playback(procs, "play-mono", args.direction, input_path, env)
            try:
                active = eventually(lambda: value if "No hardware contexts" not in
                                    (value := contexts(env)) else None, 8)
            finally:
                (output / "graph.json").write_text(command(["pw-dump"], env))
                (output / "ports-after.txt").write_text(command(["pw-link", "-iol"], env))
            (output / "device-mono.txt").write_text(active)
            time.sleep(1)
            second = contexts(env)
            (output / "device-mono-sustained.txt").write_text(second)
            owner = owned_device(second, broker.pid)
            assert owner[-1] >= 32, second
            if args.fault_service_exit:
                assert play.poll() is None
                procs.stop(broker)
                assert eventually(lambda: "No hardware contexts" in contexts(env), 5)
                assert play.poll() is None
            assert play.wait(timeout=length + 12) == 0
            if not args.fault_service_exit:
                last = contexts(env)
                (output / "device-mono-end.txt").write_text(last)
                latest = owned_device(last, broker.pid)
                commands_per_hop = 3 if tier == "light" else 2
                minimum = max(owner[-1] + 128, int(max(length - 1, 0) * 100) * commands_per_hop)
                assert latest[:3] == owner[:3] and latest[-1] >= minimum, last
            recording.send_signal(signal.SIGINT)
            recording.wait(timeout=5)
            if not args.only_mono:
                set_preset(socket_dir, args.direction, stereo)
                report = eventually(lambda: "No hardware contexts" in contexts(env), 5)
                assert report
                play = playback(procs, "play-stereo", args.direction, input_path, env)
                assert play.wait(timeout=length + 12) == 0
                assert "No hardware contexts" in contexts(env)
        assert "No hardware contexts" in contexts(env)
    pcm, rate = sf.read(output / "mono.wav", dtype="float32", always_2d=True)
    assert rate == args.rate and pcm.shape[1] == 2 and pcm.shape[0] > max(length - 1, 2) * rate
    assert np.isfinite(pcm).all() and np.array_equal(pcm[:, 0], pcm[:, 1])
    assert np.max(np.abs(pcm)) > 1e-5
    if args.fault_service_exit:
        assert np.max(np.abs(pcm[-rate:])) > 1e-5
    print(json.dumps({"passed": True, "model": args.model.name, "mono_uses_NPU": True,
                      "stereo_uses_CPU": True if not args.only_mono else None,
                      "private_graph_restored": True, "rate": args.rate,
                      "direction": args.direction, "quantum": args.quantum, "NPU_commands_lower_bound": owner[-1],
                      "NPU_commands_at_end": latest[-1] if not args.fault_service_exit else None,
                      "recorded_samples": int(pcm.shape[0]), "identical_mono_channels": True,
                      "service_exit_recovery": args.fault_service_exit}))


if __name__ == "__main__":
    main()
