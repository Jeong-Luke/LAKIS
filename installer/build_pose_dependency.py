"""Build the selective Toyxyz dependency ZIP from a frozen local source archive.

No downloads or installation writes. The output contains source-form Python/JS
and local editor assets, not control weights or SAM inference checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


REVISION = "8291d9b65d56d65be55ee0f31df073d42b7d0eb6"
UPSTREAM = "https://github.com/toyxyz/ComfyUI_toyxyz_test_nodes"
FILES = (
    "LICENSE",
    "nodes/pose3d.py",
    "nodes/pose_region_transport.py",
    "nodes/couple_region_painter.py",
    "ComfyCouple/comfy_couple.py",
    "ComfyCouple/couple_utils.py",
    "ComfyCouple/couple_patching.py",
    "ComfyCouple/couple_flux_patching.py",
    "ComfyCouple/couple_anima_patching.py",
    "ComfyCouple/couple_strategies.py",
    "ComfyCouple/flux_injection/__init__.py",
    "ComfyCouple/flux_injection/layers.py",
    "ComfyCouple/flux_injection/model.py",
    "web/pose3d_editor.js",
    "web/couple_region_painter.js",
    "web/util/pose_light_control.js",
    "web/util/pose_openpose.js",
    "web/util/pose_render_passes.js",
    "web/util/pose_body_outline.js",
    "web/util/pose_shape_control.js",
    "web/util/pose_sam_import.js",
    "web/util/pose_region_bridge.js",
    "web/util/editor_keyboard.js",
    "web/util/couple_region_painter_ui.js",
    "web/util/couple_painter_geometry.js",
    "web/util/couple_pose_source.js",
    "web/util/couple_layer_masks.js",
    "web/util/couple_mask_picker.js",
    "web/vendor/three/three.module.min.js",
    "web/vendor/three/OrbitControls.js",
    "web/vendor/three/TransformControls.js",
    "web/vendor/three/LICENSE",
    "web/vendor/three/README.md",
    "web/vendor/pose3d/mhr_female.json.gz",
    "web/vendor/pose3d/mhr_male.json.gz",
    "web/vendor/pose3d/mhr_identity45.bin.gz",
    "web/vendor/pose3d/LICENSE-MHR.txt",
    "web/vendor/pose3d/LICENSE-SAM.txt",
    "web/vendor/pose3d/NOTICE-MHR.txt",
    "web/vendor/pose3d/README.md",
)
PREFIX = "ComfyUI/custom_nodes/ComfyUI_toyxyz_test_nodes/"


def build(source_archive: Path, expected_sha256: str, output: Path):
    archive_bytes = source_archive.read_bytes()
    actual = hashlib.sha256(archive_bytes).hexdigest()
    if actual != expected_sha256.lower():
        raise ValueError("Frozen Toyxyz archive SHA-256 mismatch")
    repository = Path(__file__).resolve().parents[1]
    import io
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or set(names) != set(FILES):
            raise ValueError("Source archive must contain exactly the selected Toyxyz files")
        payloads = {name: archive.read(name) for name in FILES}
    sources = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    payloads["__init__.py"] = (
        repository / "src/custom_nodes/ComfyUI_toyxyz_test_nodes/__init__.py"
    ).read_bytes()
    payloads["web/vendor/pose3d/LICENSE-SAM.txt"] = (
        repository / "third_party_licenses/Meta-SAM-3D-Body-License.txt"
    ).read_bytes()
    provenance = {
        "upstream": UPSTREAM, "revision": REVISION, "source_archive_sha256": actual,
        "source_files": sources,
        "modifications": {
            "__init__.py": "LAKIS 8.0: register only manual pose and region nodes",
            "web/vendor/pose3d/LICENSE-SAM.txt": (
                "Restore uncorrupted SAM license from facebookresearch/sam-3d-body "
                "b5c765a0d89d789985e186d396315e7590887b94/LICENSE"
            ),
        },
        "runtime_files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in payloads.items()
        },
    }
    payloads["LAKIS_POSE_SOURCE.json"] = json.dumps(provenance, indent=2).encode("utf-8") + b"\n"
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payloads.items()):
            entry = zipfile.ZipInfo(PREFIX + name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return {
        "output": str(output), "source_archive_sha256": actual,
        "files": len(payloads), "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.source_archive, arguments.source_sha256, arguments.output), indent=2))
