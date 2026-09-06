"""Offline regression test for LAKIS' verified RealESRGAN installer."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile


def main(source_model: str, serve_ui_path: str) -> None:
    source = Path(source_model).resolve()
    expected = "F872D837D3C90ED2E05227BED711AF5671A6FD1C9F7D7E91C911A61F155E99DA"
    assert source.stat().st_size == 17_938_799
    assert hashlib.sha256(source.read_bytes()).hexdigest().upper() == expected

    ui_path = Path(serve_ui_path).resolve()
    sys.path.insert(0, str(ui_path.parent))
    spec = importlib.util.spec_from_file_location("lakis_serve_ui_test", ui_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory(prefix="lakis-upscaler-regression-") as temporary:
        root = Path(temporary)
        module.COMFY_ROOT = root

        def local_urlopen(_request, timeout=0):
            assert timeout == 60.0
            return source.open("rb")

        module.urlopen = local_urlopen
        target = root / "models" / "upscale_models" / module.REALESRGAN_MODEL

        # Exercise replacement of a truncated file, a same-size corrupt file,
        # and a missing file. Every pass must end with the pinned bytes.
        corruptions = (b"partial", b"\0" * module.REALESRGAN_BYTES, None)
        for pass_number, corrupt in enumerate(corruptions, 1):
            target.parent.mkdir(parents=True, exist_ok=True)
            if corrupt is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(corrupt)
            installed = module._ensure_realesrgan_model()
            assert installed == target
            assert installed.stat().st_size == module.REALESRGAN_BYTES
            assert hashlib.sha256(installed.read_bytes()).hexdigest().upper() == expected
            assert not installed.with_name(installed.name + ".lakis-download").exists()
            print(f"UPSCALER_VERIFIED pass={pass_number}/3")

        # A valid existing file must not contact the network again.
        module.urlopen = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected download"))
        assert module._ensure_realesrgan_model() == target
        print("UPSCALER_VALID_CACHE_OK")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: test_upscaler_download.py MODEL_PATH SERVE_UI_PATH")
    main(sys.argv[1], sys.argv[2])
