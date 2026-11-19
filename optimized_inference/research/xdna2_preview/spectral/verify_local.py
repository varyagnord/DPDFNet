"""Replay the registered WAV fixture through a spectral provider and the baseline DSP."""
import argparse
import ctypes as c
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def bind(library, name, returns, *args):
    fn = getattr(library, name)
    fn.restype, fn.argtypes = returns, list(args)
    return fn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("providers", type=Path)
    parser.add_argument("model", choices=("2", "8"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    row = json.loads(args.providers.read_text())["profiles"][args.model]
    lib = c.CDLL(row["library"])
    spectral = "dpdfnet_xdna2_spectral_"
    ptr = c.c_void_p
    manifest = row["manifest"].encode()
    assert bind(lib, spectral + "abi", c.c_uint32)() == 1
    validate = bind(lib, spectral + "validate", c.c_int, c.c_char_p)
    assert validate(manifest) == 0 and validate(b"/nonexistent.preview.json") != 0
    if not args.live:
        return
    root = Path(row["manifest"]).parent
    dsp_receipt = json.loads((root / "R101_CPU_DSP_RUNTIME_V1.json").read_text())
    dsp = c.CDLL(dsp_receipt["library"]["path"])
    make_dsp = bind(dsp, "r101_dsp_create", ptr)
    destroy_dsp = bind(dsp, "r101_dsp_destroy", c.c_int, ptr)
    ana = bind(dsp, "r101_dsp_analysis", c.c_int, ptr, ptr, c.c_size_t, ptr, c.c_size_t)
    synth = bind(dsp, "r101_dsp_synthesis", c.c_int, ptr, ptr, c.c_size_t, ptr, c.c_size_t)
    create = bind(lib, spectral + "open", ptr, c.c_char_p)
    step = bind(lib, spectral + "step", c.c_int, ptr, ptr, ptr)
    reset = bind(lib, spectral + "reset", c.c_int, ptr)
    close = bind(lib, spectral + "close", None, ptr)
    fixture = root / "r341_preview_smoke_v1"
    source, rate = sf.read(fixture / "input.wav", dtype="float32")
    expected, expected_rate = sf.read(fixture / f"m{args.model}-{row['profile']}.wav", dtype="float32")
    assert rate == expected_rate == 48000
    frames = np.pad(source, (0, 480 * 6)).reshape(-1, 480)
    output = np.empty_like(frames)
    data = np.empty(962, np.float32)
    enhanced = np.empty_like(data)
    owner = create(manifest)
    context = make_dsp()
    try:
        assert owner and context
        for x, y in zip(frames, output, strict=True):
            assert ana(context, x.ctypes.data, x.size, data.ctypes.data, data.size) == 0
            assert step(owner, data.ctypes.data, enhanced.ctypes.data) == 0
            assert synth(context, enhanced.ctypes.data, enhanced.size, y.ctypes.data, y.size) == 0
        result = output.ravel()[2400:2400 + source.size]
        assert np.array_equal(result.view("uint32"), expected.view("uint32"))
        assert reset(owner) == 0
        assert step(owner, data.ctypes.data, enhanced.ctypes.data) == 0
        print(json.dumps({"model": args.model, "reference_pcm_exact": True, "frames": int(len(frames)),
                          "reset_replay": True}))
    finally:
        if context:
            assert destroy_dsp(context) == 0
        if owner:
            close(owner)


if __name__ == "__main__":
    main()
