import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPOSITORY_ROOT / "workflows" / "LAKIS_custom_v7.3_editable.json"
EXTERNAL_UI_ROOT = REPOSITORY_ROOT / "src" / "external_ui"
sys.path.insert(0, str(EXTERNAL_UI_ROOT))

import serve_ui  # noqa: E402


class LakisDetailEditableWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        cls.nodes = {int(node["id"]): node for node in cls.graph["nodes"]}
        cls.links = {int(link[0]): link for link in cls.graph["links"]}

    def test_visual_lakis_route_is_explicit(self):
        self.assertEqual("LAKIS_VRAM_GATE", self.nodes[2202]["type"])
        self.assertEqual("LAKIS_DETAIL", self.nodes[2203]["type"])
        self.assertEqual("LAKIS_SCOPE", self.nodes[2169]["type"])
        route = self.graph["extra"]["lakis_detail_visual_contract"]["route"]
        self.assertEqual(["1633", "2202", "2203", "2169", "2170", "2171", "775"], route)

    def test_every_link_has_matching_source_and_target_slots(self):
        for link_id, link in self.links.items():
            _, source_id, source_slot, target_id, target_slot, _ = link
            source = self.nodes[int(source_id)]
            target = self.nodes[int(target_id)]
            outputs = source.get("outputs", [])
            inputs = target.get("inputs", [])
            if isinstance(outputs, dict):
                outputs = [outputs]
            if isinstance(inputs, dict):
                inputs = [inputs]
            self.assertIn(link_id, outputs[int(source_slot)].get("links") or [])
            self.assertEqual(link_id, inputs[int(target_slot)].get("link"))

    def test_lakis_mode_switch_keeps_legacy_comparison_branch(self):
        switch = self.nodes[2170]
        self.assertEqual(3774, switch["inputs"][0]["link"])
        self.assertEqual(3775, switch["inputs"][1]["link"])
        self.assertIs(True, switch["widgets_values"][0])
        self.assertEqual(1541, int(self.links[3774][1]))
        self.assertEqual(2169, int(self.links[3775][1]))

    def test_sidebar_resolves_v73_runtime_and_editable_workflows(self):
        packaged = REPOSITORY_ROOT / "workflows"
        with (
            patch.object(serve_ui, "WORKFLOW_ROOT", REPOSITORY_ROOT / "missing-user-workflows"),
            patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", packaged),
            patch.object(serve_ui, "RUNTIME_LAKIS_WORKFLOW", packaged / "LAKIS_DETAIL_runtime_api_v7.3.json"),
            patch.object(serve_ui, "EDITABLE_LAKIS_WORKFLOW", packaged / "LAKIS_custom_v7.3_editable.json"),
        ):
            runtime_path, runtime = serve_ui.resolve_lakis_workflow("runtime")
            editable_path, editable = serve_ui.resolve_lakis_workflow("editable")
        self.assertEqual("LAKIS_DETAIL_runtime_api_v7.3.json", runtime_path.name)
        self.assertEqual("LAKIS_custom_v7.3_editable.json", editable_path.name)
        self.assertEqual("LAKIS_DETAIL_runtime_api_v7.3.json", runtime_path.name)
        self.assertEqual("LAKIS_DETAIL", runtime["lakis:face_scope"]["class_type"])
        self.assertEqual("LAKIS_DETAIL", {node["id"]: node for node in editable["nodes"]}[2203]["type"])

    def test_monitor_workflow_uses_runtime_api_identity(self):
        self.assertEqual(
            "LAKIS_DETAIL_runtime_api_v7.3.json",
            serve_ui.RUNTIME_LAKIS_SOURCE_NAME,
        )
        autopatch = (
            REPOSITORY_ROOT
            / "src"
            / "custom_nodes"
            / "ComfyUI-LAKIS-AutoPatch"
            / "web"
            / "lakis_autopatch.js"
        ).read_text(encoding="utf-8")
        self.assertIn("lakis_autopatch_display_name", autopatch)
        self.assertIn("app.loadApiJson(workflow, displayName)", autopatch)
        self.assertNotIn(
            'app.loadGraphData(workflow, true, true, "LAKIS_custom_v7.1.json")',
            autopatch,
        )

    def test_runtime_monitor_never_falls_back_to_user_editable_workflow(self):
        packaged = REPOSITORY_ROOT / "workflows"
        with (
            patch.object(serve_ui, "WORKFLOW_ROOT", packaged),
            patch.object(serve_ui, "PACKAGED_WORKFLOW_ROOT", packaged),
            patch.object(serve_ui, "RUNTIME_LAKIS_WORKFLOW", packaged / "missing-runtime-api.json"),
            patch.object(serve_ui, "PREFERRED_LAKIS_WORKFLOW", packaged / "LAKIS_custom_v7.3_editable.json"),
        ):
            with self.assertRaises(FileNotFoundError):
                serve_ui.resolve_lakis_workflow("runtime")


if __name__ == "__main__":
    unittest.main(verbosity=2)
