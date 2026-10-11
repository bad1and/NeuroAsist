"""A detached Windows console must not prevent model loading."""
import io
import os

import pytest

from apps.backend import desktop_entry


class BrokenConsole:
    def flush(self):
        raise OSError(22, "Invalid argument")

    def write(self, _value):
        raise OSError(22, "Invalid argument")


@pytest.mark.parametrize("stream", [None, BrokenConsole()])
def test_desktop_repairs_missing_or_invalid_console_before_hub_progress(monkeypatch, stream):
    good_stdout = io.StringIO()
    monkeypatch.setattr(desktop_entry.sys, "stdout", good_stdout)
    monkeypatch.setattr(desktop_entry.sys, "stderr", stream)
    desktop_entry.configure_standard_streams()
    repaired = desktop_entry.sys.stderr
    try:
        assert desktop_entry.sys.stdout is good_stdout
        repaired.write("Model diagnostic\n")
        repaired.flush()
        from huggingface_hub.utils import tqdm
        assert list(tqdm(range(2), desc="Model loading")) == [0, 1]
    finally:
        repaired.close()


def test_desktop_disables_hub_progress_before_importing_models():
    assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
