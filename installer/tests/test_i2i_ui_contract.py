from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPOSITORY_ROOT / "src" / "external_ui" / "app.js"
INDEX_HTML = REPOSITORY_ROOT / "src" / "external_ui" / "index.html"


class I2iUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP_JS.read_text(encoding="utf-8")
        cls.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_enabling_i2i_disables_composition_and_shows_notice(self):
        start = self.app.index("function setI2iEnabled(enabled)")
        end = self.app.index("\n}\n\nlet i2iNoticeTimer", start)
        function = self.app[start:end]
        self.assertIn("setCompositionEnabled(false);", function)
        self.assertIn("showI2iCompositionNotice();", function)
        self.assertIn('id="i2iCompositionNotice"', self.html)
        self.assertIn("i2i를 사용하면 구도 설정이 꺼집니다.", self.html)

    def test_completed_i2i_generation_sets_visible_badge_contract(self):
        self.assertIn('thumb.dataset.i2i = String(status.i2i_enabled === true);', self.app)
        self.assertIn('document.querySelector("#previewI2i").hidden = thumb.dataset.i2i !== "true";', self.app)
        self.assertIn('<span id="previewI2i" hidden>i2i</span>', self.html)

    def test_history_selection_restores_prompt_metadata(self):
        self.assertIn("thumb._lakisPrompt = status.prompt_used", self.app)
        self.assertIn("setCurrentPreviewPrompt(thumb._lakisPrompt);", self.app)

    def test_translation_replaces_only_generation_payload_prompt(self):
        self.assertIn("const generationPayload = structuredClone(state);", self.app)
        self.assertIn("generationPayload.prompt = await translatedPromptForGeneration(activePrompt);", self.app)
        self.assertIn('state.prompt_enabled[key] === false ? "" : value', self.app)
        self.assertIn("body: JSON.stringify({ prompt: original })", self.app)
        self.assertIn("return result.prompt;", self.app)


if __name__ == "__main__":
    unittest.main()
