from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class PromptFieldToggleTests(unittest.TestCase):
    def test_all_nine_prompt_fields_have_toggle_bindings(self):
        app = (REPOSITORY_ROOT / "src" / "external_ui" / "app.js").read_text(encoding="utf-8")
        for key in (
            "fixed", "general", "quality", "artist", "trigger", "negative_fixed",
            "negative_quality", "negative_artist", "negative",
        ):
            self.assertIn(f'"{key}"', app)
        self.assertIn("prompt-field-toggle", app)
        self.assertIn("state.prompt_enabled[key]", app)
        self.assertIn('state.prompt_enabled[key] === false ? "" : value', app)

    def test_toggle_state_is_persisted_by_backend(self):
        bridge = (REPOSITORY_ROOT / "src" / "external_ui" / "workflow_bridge.py").read_text(encoding="utf-8")
        server = (REPOSITORY_ROOT / "src" / "external_ui" / "serve_ui.py").read_text(encoding="utf-8")
        self.assertIn('"prompt_enabled": enabled', bridge)
        self.assertIn('incoming.get("prompt_enabled")', server)

    def test_prompt_switches_use_the_standard_blue_active_color(self):
        css = (REPOSITORY_ROOT / "src" / "external_ui" / "prompt-categories.css").read_text(encoding="utf-8")
        self.assertIn("background:#3f70d9", css)
        self.assertNotIn("background:#d94f93", css)


if __name__ == "__main__":
    unittest.main()
