"""48 kHz mono WAV example with causal FFT and delay-aligned output."""
import argparse
from pathlib import Path
import numpy as np
import soundfile as sf
from dpdfnet import Model


def window():
    n = np.arange(960, dtype=np.float64)
    return np.sin(0.5 * np.pi * np.sin(np.pi * (n + 0.5) / 960)**2).astype(np.float32)


def spectra(audio):
    count = (audio.size + 479) // 480 + 6
    padded = np.pad(audio, (480, count * 480 - audio.size))
    win = window()
    for index in range(count):
        value = np.fft.rfft(padded[index * 480:index * 480 + 960] * win)
        result = np.empty((481, 2), dtype=np.float32)
        result[:, 0], result[:, 1] = value.real, value.imag
        yield result


def enhance(model, audio):
    model.reset()
    win = window()
    overlap = np.zeros(960, dtype=np.float32)
    chunks = []
    for spectrum in spectra(audio):
        result = model.process(spectrum)
        time_frame = np.fft.irfft(result[:, 0] + 1j * result[:, 1], n=960).astype(np.float32) * win
        overlap[:480] = overlap[480:]; overlap[480:] = 0
        overlap += time_frame
        chunks.append(overlap[:480].copy())
    return np.concatenate(chunks)[2400:2400 + audio.size]


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=int, choices=(2, 8), default=8)
    parser.add_argument("--library", type=Path, help="CPU library (default: build/libdpdfnet.so)")
    parser.add_argument("--backend", choices=("cpu", "xdna2"), default="cpu")
    parser.add_argument("--xdna-root", type=Path, help="Qualified local XDNA2 preview artifact directory")
    parser.add_argument("--profile", help="Explicit XDNA2 numerical profile")
    args = parser.parse_args()
    if args.backend == "xdna2" and args.xdna_root is None:
        parser.error("--backend xdna2 requires --xdna-root")
    if args.backend == "xdna2" and args.library is not None:
        parser.error("--library selects a CPU library")
    if args.backend == "cpu" and (args.xdna_root is not None or args.profile is not None):
        parser.error("--xdna-root and --profile require --backend xdna2")
    audio, rate = sf.read(args.input, dtype="float32", always_2d=True)
    if rate != 48000 or audio.shape[1] != 1 or not np.isfinite(audio).all():
        raise ValueError("Input must be finite 48 kHz mono audio; no implicit resampling")
    if args.backend == "xdna2":
        from xdna2_preview import enhance as enhance_xdna2

        output = enhance_xdna2(audio[:, 0], args.xdna_root, args.model, args.profile)
    else:
        weights = root / "models" / ("dpdfnet%d_48khz_hr" % args.model) / "weights.f32"
        with Model(args.library or root / "build/libdpdfnet.so", weights, args.model) as model:
            output = enhance(model, audio[:, 0])
    sf.write(args.output, output, rate, subtype="FLOAT")


if __name__ == "__main__":
    main()
