"""PyInstaller hook for the CPU base Iris desktop runtime.

The application defaults to CPU inference.  A CUDA-enabled development wheel
contains several gigabytes of optional CUDA DLLs; including them makes an NSIS
installer exceed its 2 GiB mmap limit.  Keep the CPU PyTorch runtime required by
the shipped STT/TTS paths and deliberately omit CUDA-only DLLs.

GPU distribution is a separate, explicit release concern rather than an
accidental property of the build machine's virtual environment.
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


module_collection_mode = "pyz+py"
datas = collect_data_files(
    "torch",
    excludes=[
        "**/*.h",
        "**/*.hpp",
        "**/*.cuh",
        "**/*.lib",
        "**/*.cpp",
        "**/*.pyi",
        "**/*.cmake",
        # DLLs are added below via the filtered binary list. If they are left
        # here, PyInstaller reclassifies them as binaries after the hook runs.
        "**/*.dll",
    ],
)
hiddenimports = collect_submodules("torch")
CUDA_LIBRARY_PREFIXES = (
    "c10_cuda",
    "caffe2_nvrtc",
    "cublas",
    "cuda",
    "cudart",
    "cudnn",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "cupti",
    "nvjitlink",
    "nvperf",
    "nvrtc",
    "nvtoolsext",
    "torch_cuda",
)


def _is_cuda_library(source: str) -> bool:
    return Path(source).name.lower().startswith(CUDA_LIBRARY_PREFIXES)


binaries = [
    (source, destination)
    for source, destination in collect_dynamic_libs("torch")
    if not _is_cuda_library(source)
]
