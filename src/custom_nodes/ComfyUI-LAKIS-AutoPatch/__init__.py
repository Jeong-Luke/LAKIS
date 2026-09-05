# SPDX-License-Identifier: MIT
# LAKIS AutoPatch Bridge
#
# One purpose only:
# after an AutoPatch restart, serve startup_workflow.json to the frontend once.

from __future__ import annotations

import json
from pathlib import Path

WEB_DIRECTORY = "./web"

_marker = Path(__file__).resolve().parent / "startup_workflow.json"

try:
    from aiohttp import web
    from server import PromptServer

    @PromptServer.instance.routes.get("/lakis/autopatch/startup-workflow")
    async def lakis_autopatch_get_startup_workflow(request):
        if not _marker.exists():
            return web.Response(status=204)

        try:
            data = json.loads(_marker.read_text(encoding="utf-8"))
            return web.json_response(data)
        except Exception as e:
            return web.json_response(
                {"error": f"Failed to read startup workflow: {e}"},
                status=500,
            )

    @PromptServer.instance.routes.post("/lakis/autopatch/consume-startup-workflow")
    async def lakis_autopatch_consume_startup_workflow(request):
        try:
            if _marker.exists():
                _marker.unlink()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

except Exception as e:
    print(f"[LAKIS AutoPatch] route setup skipped: {e}")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
