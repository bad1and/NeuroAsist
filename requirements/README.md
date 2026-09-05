# Python dependency profiles

`runtime.txt` contains the direct dependencies bundled into the desktop
sidecar. `dev.txt` adds repository tests and benchmarks. `build.txt` adds the
release packager. The root `requirements.txt` remains the convenient developer
entry point.

`torch-cpu.txt` and `torch-cu128.txt` select the wheel channel before the main
profile is installed. The release script always selects `torch-cpu.txt`; CUDA
is a separate artifact, never an accidental property of the build machine.

Only direct dependencies belong in the three profiles. `constraints.txt` pins
the tested transitive graph without installing anything by itself. Resolve and
review that graph in a clean CPython 3.12 environment; copying `pip freeze` from
a long-lived environment would reintroduce abandoned libraries.

The supported Windows release script always recreates
`build/release-venv` from `build.txt`. A developer `.venv` is never used as the
PyInstaller input, so packages left from experiments cannot leak into an
installer.

Run `python scripts/check_python_dependencies.py` to verify that the active
environment satisfies the resolved graph. Release packaging runs it with
`--strict`, which also rejects every undeclared installed package.

`qwen-asr` and `qwen-tts` are benchmark-only optional integrations and are not
part of the supported Iris 1.0 runtime. Their benchmark scripts intentionally
accept an isolated Python environment.
