# SPDX-FileCopyrightText: 2026 Luke Jeong
# SPDX-License-Identifier: MIT
# LAKIS AutoPatch Bridge
#
# One purpose only:
# after an AutoPatch restart, serve startup_workflow.json to the frontend once.

from __future__ import annotations

import hashlib
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
            raw = _marker.read_bytes()
            data = json.loads(raw.decode("utf-8-sig"))
            return web.json_response(data, headers={
                "X-LAKIS-Marker-SHA256": hashlib.sha256(raw).hexdigest(),
                "Cache-Control": "no-store",
            })
        except Exception as e:
            return web.json_response(
                {"error": f"Failed to read startup workflow: {e}"},
                status=500,
            )

    # Optimistic stale-response guard; cross-process compare/unlink races still
    # require a request-scoped queue if multiple producers share this marker.
    @PromptServer.instance.routes.post("/lakis/autopatch/consume-startup-workflow")
    async def lakis_autopatch_consume_startup_workflow(request):
        try:
            if _marker.exists():
                expected = request.headers.get("X-LAKIS-Marker-SHA256", "")
                if not expected:
                    # An old client cannot safely acknowledge an identified
                    # marker. Leave it intact rather than delete new work.
                    return web.json_response({"ok": False, "reason": "marker_identity_required"}, status=409)
                raw = _marker.read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    return web.json_response({"ok": False, "reason": "marker_changed"}, status=409)
                _marker.unlink()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

except Exception as e:
    print(f"[LAKIS AutoPatch] route setup skipped: {e}")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
