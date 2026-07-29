"""Process-wide voice runtime policies."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def configure_torch_threads(cpu_threads: int, interop_threads: int) -> dict[str, int]:
    """Configure PyTorch exactly once before any voice model is loaded."""
    import torch

    cpu_threads = max(1, int(cpu_threads))
    interop_threads = max(1, int(interop_threads))
    torch.set_num_threads(cpu_threads)
    try:
        torch.set_num_interop_threads(interop_threads)
    except RuntimeError:
        # PyTorch forbids changing interop threads after parallel work starts.
        # Startup tests may create multiple app instances in one process.
        if torch.get_num_interop_threads() != interop_threads:
            logger.warning(
                "PyTorch interop threads were already initialized: active=%s requested=%s",
                torch.get_num_interop_threads(),
                interop_threads,
            )
    active = {
        "cpu_threads": torch.get_num_threads(),
        "interop_threads": torch.get_num_interop_threads(),
    }
    logger.info("Voice PyTorch threading configured: %s", active)
    return active
