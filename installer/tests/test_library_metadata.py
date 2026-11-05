from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, PngImagePlugin


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src" / "external_ui"))

import serve_ui  # noqa: E402


CHECKPOINT = "fnMomentAnimaTurbo_v40NoTurbo.safetensors"


def graph(*, sam=False, lllite=False, loras=None):
    value = {
        "890:1365": {
            "class_type": "DiffusionModelLoaderKJ",
            "inputs": {"model_name": CHECKPOINT},
        },
        "1925": {
            "class_type": "EasyUseAnimaLoraPreset",
            "inputs": {"loras": json.dumps(loras or [])},
        },
    }
    if sam:
        value["893:891"] = {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"},
        }
    if lllite:
        value["lllite"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "anima-lllite-inpainting-v2.safetensors", "strength_model": 1},
        }
    return value


class LibraryMetadataTests(unittest.TestCase):
    def image_metadata(self, value, image_format="PNG"):
        with tempfile.TemporaryDirectory(prefix="lakis-library-metadata-") as directory:
            path = Path(directory) / ("image." + image_format.lower())
            options = {}
            if image_format == "PNG":
                metadata = PngImagePlugin.PngInfo()
                if value is not None:
                    metadata.add_text("prompt", value)
                options["pnginfo"] = metadata
            else:
                exif = Image.Exif()
                exif[272] = "prompt:" + value
                options["exif"] = exif
            with Image.new("RGB", (8, 8), "blue") as image:
                image.save(path, format=image_format, **options)
            return serve_ui._image_prompt_metadata(path)

    def assert_checkpoint(self, value):
        self.assertEqual(CHECKPOINT, serve_ui._prompt_graph_metadata(value)["checkpoint"])

    def test_case_a_checkpoint_only(self):
        self.assert_checkpoint(graph())

    def test_case_b_checkpoint_and_sam3(self):
        self.assert_checkpoint(graph(sam=True))

    def test_case_c_checkpoint_and_lllite(self):
        self.assert_checkpoint(graph(lllite=True))

    def test_case_d_checkpoint_sam3_and_lllite(self):
        self.assert_checkpoint(graph(sam=True, lllite=True))

    def test_case_e_enabled_lora(self):
        metadata = serve_ui._prompt_graph_metadata(graph(loras=[{"name": "enabled.safetensors", "on": True, "strength": 0.7}]))
        self.assertEqual([{"name": "enabled.safetensors", "strength": 0.7}], metadata["loras"])

    def test_case_f_disabled_lora(self):
        rows = [
            {"name": "enabled.safetensors", "on": True, "strength": 0.7},
            {"name": "disabled.safetensors", "on": False, "strength": 1.0},
        ]
        self.assertEqual([{"name": "enabled.safetensors", "strength": 0.7}], serve_ui._prompt_graph_metadata(graph(loras=rows))["loras"])

    def test_case_g_delete_mode_lora_stack_is_disabled(self):
        rows = [{"name": "ui-enabled.safetensors", "on": False, "strength": 1.0}]
        self.assertEqual([], serve_ui._prompt_graph_metadata(graph(loras=rows))["loras"])

    def test_anima_png_prompt_metadata(self):
        rows = [{"name": "enabled.safetensors", "on": True, "strength": 0.7}]
        metadata = self.image_metadata(json.dumps(graph(sam=True, loras=rows)))
        self.assertEqual(CHECKPOINT, metadata["checkpoint"])
        self.assertEqual([{"name": "enabled.safetensors", "strength": 0.7}], metadata["loras"])

    def test_native_anima_loader_checkpoint(self):
        value = graph(sam=True, lllite=True)
        value["890:1365"]["class_type"] = "LAKIS_DiffusionModelLoader"
        for image_format in ("PNG", "WEBP"):
            with self.subTest(image_format=image_format):
                metadata = self.image_metadata(json.dumps(value), image_format)
                self.assertEqual(CHECKPOINT, metadata["checkpoint"])

    def test_moss_png_linked_prompt_metadata(self):
        value = serve_ui.moss_workflows.load_api()
        value["775"].setdefault("_meta", {})["generation_engine"] = "moss"
        for name, data in {
            "positive": "파란 집, green meadow",
            "negative": "blurry, low quality",
            "seed_value": 81010,
            "modelname": "moss_image_sft_int8_convrot.safetensors",
        }.items():
            serve_ui.moss_workflows.set_input(value, "775", name, data)
        self.assertEqual({
            "engine": "moss", "checkpoint": "moss_image_sft_int8_convrot.safetensors",
            "loras": [], "seed": 81010, "prompt": "파란 집, green meadow",
            "negative_prompt": "blurry, low quality",
        }, self.image_metadata(json.dumps(value, ensure_ascii=False)))

    def test_missing_invalid_or_non_graph_png_metadata(self):
        for value in (None, "{invalid", "[]"):
            with self.subTest(value=value):
                self.assertEqual({
                    "checkpoint": "확인할 수 없음", "loras": [], "seed": None,
                    "prompt": "", "negative_prompt": "",
                }, self.image_metadata(value))

    def test_webp_exif_metadata_is_preserved(self):
        metadata = self.image_metadata(json.dumps(graph(sam=True)), "WEBP")
        self.assertEqual(CHECKPOINT, metadata["checkpoint"])

    def test_jpeg_exif_metadata_is_preserved(self):
        metadata = self.image_metadata(json.dumps(graph(sam=True)), "JPEG")
        self.assertEqual(CHECKPOINT, metadata["checkpoint"])


if __name__ == "__main__":
    unittest.main()
