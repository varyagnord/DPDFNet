#!/usr/bin/env python3
"""Build an optional, pinned real-HushMic measurement adapter offline."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--hushmic-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--clock-dir',type=Path,required=True);a=p.parse_args()
 root=a.hushmic_root.resolve();out=a.output.resolve();clock=a.clock_dir.resolve()
 crate=root/'crates/hushmic-denoiser';assert (crate/'Cargo.toml').is_file() and (clock/'libaudio_clock.so').is_file()
 bridge=crate/'bridge.c'
 if not bridge.is_file() or 'DPDF_QA_LIBRARY' not in bridge.read_text() or 'dpdfnet_process' not in bridge.read_text() or 'bridge.c' not in (crate/'build.rs').read_text():
  raise ValueError('A reviewed test-only public-runtime bridge is required; refusing to benchmark an unrelated vendored engine')
 out.mkdir(parents=True,exist_ok=False);(out/'src').mkdir()
 manifest='''[package]
name="dpdf-audio-native-lab"
version="0.0.0"
edition="2021"
[workspace]
[lib]
crate-type=["cdylib"]
[dependencies]
hushmic-denoiser={path='''+json.dumps(str(crate))+''',features=["native"]}
'''
 (out/'Cargo.toml').write_text(manifest)
 (out/'build.rs').write_text('fn main(){println!("cargo:rustc-link-search=native={} ", std::env::var("DPDF_AUDIO_CLOCK_DIR").unwrap().trim());println!("cargo:rustc-link-lib=audio_clock");println!("cargo:rustc-link-arg=-Wl,-rpath,{}",std::env::var("DPDF_AUDIO_CLOCK_DIR").unwrap());}\n'.replace('{} ','{}'))
 template=Path(__file__).with_name('audio_native.rs');(out/'src/lib.rs').write_bytes(template.read_bytes())
 env=os.environ.copy();env.update(DPDF_AUDIO_CLOCK_DIR=str(clock),CARGO_TARGET_DIR=str(out/'target'))
 subprocess.run(['cargo','build','--offline','--release','--manifest-path',str(out/'Cargo.toml')],env=env,check=True)
 files={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(root.rglob('*')) if f.is_file() and (f.suffix in ['.rs','.c','.h'] or f.name in ['Cargo.toml','Cargo.lock']) and not any(x in ['target','.git'] for x in f.relative_to(root).parts)}
 lib=out/'target/release/libdpdf_audio_native_lab.so'
 (out/'provenance.json').write_text(json.dumps(dict(source_root=str(root),source_files=files,template_sha256=hashlib.sha256(template.read_bytes()).hexdigest(),clock_sha256=hashlib.sha256((clock/'libaudio_clock.so').read_bytes()).hexdigest(),binary=str(lib),binary_sha256=hashlib.sha256(lib.read_bytes()).hexdigest(),cargo_lock_sha256=hashlib.sha256((out/'Cargo.lock').read_bytes()).hexdigest(),offline=True),indent=2)+'\n')
if __name__=='__main__':main()
