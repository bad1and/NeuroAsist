from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class LocalStressAccentor:
    """Optional local Russian stress marker with a safe built-in fallback."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cpu_threads: int = 1,
        loader: Callable[[], Callable[[str], str] | None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.cpu_threads = max(1, cpu_threads)
        self._loader = loader
        self._accentor: Callable[[str], str] | None = None
        self._attempted = False
        self._load_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self._accentor is not None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        return "ready" if self.ready else "fallback"

    async def preload(self) -> bool:
        if not self.enabled or self._attempted:
            return self.ready
        async with self._load_lock:
            if self._attempted:
                return self.ready
            self._attempted = True
            try:
                self._accentor = await asyncio.to_thread(self._load_sync)
                if self._accentor is None:
                    raise RuntimeError("Silero Stress returned no accentor")
                logger.info(
                    "Silero Stress accentor loaded: device=cpu cpu_threads=%s",
                    self.cpu_threads,
                )
            except Exception as exc:
                # Speech must remain available: v5_5_ru has its own automatic stress.
                self._accentor = None
                logger.warning(
                    "Silero Stress accentor is unavailable; falling back to built-in Silero stress: "
                    "error_type=%s",
                    type(exc).__name__,
                )
        return self.ready

    def accent(self, text: str) -> str:
        if not text or self._accentor is None:
            return text
        try:
            rendered = self._accentor(text)
        except Exception as exc:
            logger.warning(
                "Silero Stress accentuation failed; using built-in Silero stress: error_type=%s",
                type(exc).__name__,
            )
            return text
        return rendered if isinstance(rendered, str) and rendered.strip() else text

    def _load_sync(self) -> Callable[[str], str] | None:
        if self._loader is not None:
            return self._loader()
        # The package itself uses one CPU thread by default.  Import it before
        # loading Silero TTS so the TTS provider can restore its own thread count.
        from silero_stress import load_accentor

        return load_accentor()
