"""Exercise the actual HushMic LADSPA module on a private session bus."""
import argparse
import ctypes as c
import json
import math
import os
from pathlib import Path
import time

HANDLE = c.c_void_p
ULONG = c.c_ulong
AUDIO = c.c_float * 480
INSTANTIATE = c.CFUNCTYPE(HANDLE, HANDLE, ULONG)
CONNECT = c.CFUNCTYPE(None, HANDLE, ULONG, c.POINTER(c.c_float))
STATE = c.CFUNCTYPE(None, HANDLE)
RUN = c.CFUNCTYPE(None, HANDLE, ULONG)


class Descriptor(c.Structure):
    _fields_ = [
        ("id", ULONG), ("label", c.c_char_p), ("properties", c.c_int),
        ("name", c.c_char_p), ("maker", c.c_char_p), ("copyright", c.c_char_p),
        ("ports", ULONG), ("port_kinds", c.c_void_p), ("port_names", c.POINTER(c.c_char_p)),
        ("port_hints", c.c_void_p), ("impl_data", HANDLE),
        ("instantiate", INSTANTIATE), ("connect", CONNECT), ("activate", STATE),
        ("run", RUN), ("run_adding", HANDLE), ("gain_adding", HANDLE),
        ("deactivate", STATE), ("cleanup", STATE),
    ]


def worker(path, mono, frames):
    dylib = c.CDLL(str(path))
    dylib.ladspa_descriptor.argtypes = [ULONG]
    dylib.ladspa_descriptor.restype = c.POINTER(Descriptor)
    dsp = dylib.ladspa_descriptor(0)
    assert dsp.contents.label == b"dpdfnet_mono" and dsp.contents.id == 0x68736D31
    assert list(dsp.contents.port_names[:dsp.contents.ports]) == [
        b"Input", b"Output", b"Attenuation Limit (dB)", b"Mode"]
    prepare = dylib.hushmic_dpdfnet_prepare_xdna2_v1
    prepare.argtypes = [c.c_bool]
    prepare.restype = c.c_uint64
    status = dylib.hushmic_dpdfnet_status_xdna2_v1
    status.argtypes = [c.c_uint64]
    status.restype = c.c_uint32
    set_policy = dylib.hushmic_dpdfnet_set_policy_xdna2_v1
    set_policy.argtypes = [c.c_uint8]
    set_policy.restype = c.c_int32
    assert set_policy(2) == 0
    ticket = prepare(mono)
    f = dsp.contents
    handle = f.instantiate(c.cast(dsp, HANDLE), 48000)
    assert handle
    audio_in, audio_out = AUDIO(), AUDIO()
    attenuation, mode = c.c_float(65), c.c_float(0)
    try:
        for i, buf in enumerate((audio_in, audio_out, c.byref(attenuation), c.byref(mode))):
            f.connect(handle, i, c.cast(buf, c.POINTER(c.c_float)))
        f.activate(handle)
        statuses = []
        audio_peak = 0
        start = time.monotonic()
        for frame in range(frames):
            for i in range(480):
                audio_in[i] = 0.05 * math.sin((480 * frame + i) * 0.041)
            if frame == frames - 30:
                assert set_policy(0) == 0
            f.run(handle, 480)
            observed = status(ticket)
            if not statuses or observed != statuses[-1][1]:
                statuses.append([frame, observed])
            if statuses and observed in (0, 2, 3):
                audio_peak = max(audio_peak, max(abs(value) for value in audio_out))
            time.sleep(max(0, start + (frame + 1) / 100 - time.monotonic()))
        result = {"statuses": statuses, "frames": frames, "peak": audio_peak, "mono": mono}
        print(json.dumps(result), flush=True)
        assert audio_peak > 0
        if mono:
            assert any(code == 2 for _, code in statuses), result
            assert statuses[-1][1] == 0, result
        else:
            assert all(code == 3 for _, code in statuses), result
    finally:
        f.deactivate(handle)
        f.cleanup(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("--stereo", action="store_true")
    parser.add_argument("--frames", type=int, default=300)
    args = parser.parse_args()
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        parser.error("a private D-Bus session is required")
    worker(args.library.resolve(strict=True), not args.stereo, args.frames)


if __name__ == "__main__":
    main()
