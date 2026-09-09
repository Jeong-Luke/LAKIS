"""Build the human-editable LAKIS DETAIL ComfyUI workflow."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "workflows" / "LAKIS_custom_v7.1_editable.json"
TARGET = ROOT / "workflows" / "LAKIS_custom_v7.3_editable.json"
RUNTIME_TARGET = ROOT / "workflows" / "LAKIS_runtime_visual_v7.3.json"


def main() -> None:
    graph = json.loads(SOURCE.read_text(encoding="utf-8"))
    nodes = {int(node["id"]): node for node in graph["nodes"]}

    # Idempotently rebuild the three LAKIS nodes and their links.
    managed_nodes = {2202, 2203}
    managed_links = set(range(3786, 3799)) | {3764}
    graph["nodes"] = [node for node in graph["nodes"] if int(node["id"]) not in managed_nodes]
    graph["links"] = [link for link in graph["links"] if int(link[0]) not in managed_links]

    def slots(value):
        if isinstance(value, list):
            return value
        return [value] if isinstance(value, dict) else []

    for node in graph["nodes"]:
        for item in slots(node.get("inputs")):
            if item.get("link") in managed_links:
                item["link"] = None
        for item in slots(node.get("outputs")):
            item["links"] = [link for link in (item.get("links") or []) if link not in managed_links]

    nodes = {int(node["id"]): node for node in graph["nodes"]}
    scope = nodes[2169]
    scope["pos"] = [-3900, 3720]
    scope["flags"] = {"collapsed": False, "pinned": True}
    scope["title"] = "LAKIS_SCOPE · 타일 업스케일"
    scope["inputs"][0]["link"] = 3798
    nodes[2170]["pos"] = [-3450, 3740]
    nodes[2170]["title"] = "DETAIL 경로 전환 · OFF 레거시 / ON LAKIS"
    nodes[2170]["widgets_values"] = [True]
    nodes[2171]["title"] = "DETAIL 업스케일 공통 ON / OFF"

    gate = {
        "id": 2202,
        "type": "LAKIS_VRAM_GATE",
        "pos": [-4740, 3740],
        "size": [300, 118],
        "flags": {"collapsed": False, "pinned": True},
        "order": 114,
        "mode": 0,
        "inputs": [
            {"name": "image", "type": "IMAGE", "link": 3786},
            {"name": "min_free_gb", "type": "FLOAT", "widget": {"name": "min_free_gb"}, "link": None},
            {"name": "empty_cache", "type": "BOOLEAN", "widget": {"name": "empty_cache"}, "link": None},
        ],
        "outputs": [
            {"name": "image", "type": "IMAGE", "links": [3787]},
            {"name": "diagnostics", "type": "STRING", "links": []},
        ],
        "title": "LAKIS VRAM Gate · HighRez → Detail",
        "properties": {"Node name for S&R": "LAKIS_VRAM_GATE"},
        "widgets_values": [1.5, True],
        "color": "#533043",
        "bgcolor": "#321d2a",
    }
    detail = {
        "id": 2203,
        "type": "LAKIS_DETAIL",
        "pos": [-4380, 3660],
        "size": [420, 790],
        "flags": {"collapsed": False, "pinned": True},
        "order": 115,
        "mode": 0,
        "inputs": [
            {"name": "image", "type": "IMAGE", "link": 3787},
            {"name": "face_segs", "type": "SEGS", "link": 3788},
            {"name": "model", "type": "MODEL", "link": 3789},
            {"name": "clip", "type": "CLIP", "link": 3790},
            {"name": "vae", "type": "VAE", "link": 3791},
            {"name": "positive", "type": "CONDITIONING", "link": 3792},
            {"name": "negative", "type": "CONDITIONING", "link": 3793},
            {"name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": 3794},
            {"name": "steps", "type": "INT", "widget": {"name": "steps"}, "link": None},
            {"name": "cfg", "type": "FLOAT", "widget": {"name": "cfg"}, "link": 3795},
            {"name": "sampler_name", "type": "COMBO", "widget": {"name": "sampler_name"}, "link": 3796},
            {"name": "scheduler", "type": "COMBO", "widget": {"name": "scheduler"}, "link": 3797},
            {"name": "face_guide_size", "type": "INT", "widget": {"name": "face_guide_size"}, "link": None},
            {"name": "face_max_size", "type": "INT", "widget": {"name": "face_max_size"}, "link": None},
            {"name": "face_denoise", "type": "FLOAT", "widget": {"name": "face_denoise"}, "link": None},
            {"name": "face_feather", "type": "INT", "widget": {"name": "face_feather"}, "link": None},
            {"name": "eye_refine", "type": "BOOLEAN", "widget": {"name": "eye_refine"}, "link": None},
            {"name": "eye_strength", "type": "FLOAT", "widget": {"name": "eye_strength"}, "link": None},
            {"name": "eye_y", "type": "FLOAT", "widget": {"name": "eye_y"}, "link": None},
            {"name": "eye_spacing", "type": "FLOAT", "widget": {"name": "eye_spacing"}, "link": None},
            {"name": "eye_width", "type": "FLOAT", "widget": {"name": "eye_width"}, "link": None},
            {"name": "eye_height", "type": "FLOAT", "widget": {"name": "eye_height"}, "link": None},
            {"name": "eye_radius", "type": "INT", "widget": {"name": "eye_radius"}, "link": None},
            {"name": "eye_color_preservation", "type": "FLOAT", "widget": {"name": "eye_color_preservation"}, "link": None},
            {"name": "unload_after", "type": "BOOLEAN", "widget": {"name": "unload_after"}, "link": None},
            {"name": "multi_face_quality", "type": "BOOLEAN", "widget": {"name": "multi_face_quality"}, "link": None},
            {"name": "multi_face_crop_factor", "type": "FLOAT", "widget": {"name": "multi_face_crop_factor"}, "link": None},
            {"name": "multi_face_guide_size", "type": "INT", "widget": {"name": "multi_face_guide_size"}, "link": None},
            {"name": "multi_face_steps", "type": "INT", "widget": {"name": "multi_face_steps"}, "link": None},
            {"name": "multi_face_denoise", "type": "FLOAT", "widget": {"name": "multi_face_denoise"}, "link": None},
            {"name": "multi_face_eye_strength", "type": "FLOAT", "widget": {"name": "multi_face_eye_strength"}, "link": None},
        ],
        "outputs": [
            {"name": "image", "type": "IMAGE", "links": [3798]},
            {"name": "eye_mask", "type": "MASK", "links": []},
            {"name": "debug_image", "type": "IMAGE", "links": []},
            {"name": "diagnostics", "type": "STRING", "links": []},
        ],
        "title": "LAKIS_DETAIL · 얼굴 1회 + 눈 경량 보정",
        "properties": {"Node name for S&R": "LAKIS_DETAIL"},
        "widgets_values": [0, 8, 5.0, "euler", "normal", 768, 1280, 0.24, 8, True,
                           0.22, 0.42, 0.34, 0.24, 0.14, 2, 0.85, False,
                           True, 2.2, 768, 8, 0.25, 0.18],
        "color": "#533043",
        "bgcolor": "#321d2a",
    }
    graph["nodes"].extend([gate, detail])

    new_links = [
        [3786, 1633, 0, 2202, 0, "IMAGE"],
        [3787, 2202, 0, 2203, 0, "IMAGE"],
        [3788, 1530, 1, 2203, 1, "SEGS"],
        [3789, 2167, 1, 2203, 2, "MODEL"],
        [3790, 2167, 2, 2203, 3, "CLIP"],
        [3791, 2167, 3, 2203, 4, "VAE"],
        [3792, 2167, 4, 2203, 5, "CONDITIONING"],
        [3793, 2167, 5, 2203, 6, "CONDITIONING"],
        [3794, 2167, 8, 2203, 7, "INT"],
        [3795, 2167, 11, 2203, 9, "FLOAT"],
        [3796, 2167, 13, 2203, 10, "COMBO"],
        [3797, 2167, 14, 2203, 11, "COMBO"],
        [3798, 2203, 0, 2169, 0, "IMAGE"],
    ]
    graph["links"].extend(new_links)

    def add_output_link(node_id: int, slot: int, link_id: int) -> None:
        output = slots(nodes[node_id].get("outputs"))[slot]
        output.setdefault("links", [])
        if link_id not in output["links"]:
            output["links"].append(link_id)

    add_output_link(1633, 0, 3786)
    add_output_link(1530, 1, 3788)
    for slot, link_id in ((1, 3789), (2, 3790), (3, 3791), (4, 3792), (5, 3793),
                          (8, 3794), (11, 3795), (13, 3796), (14, 3797)):
        add_output_link(2167, slot, link_id)

    graph["groups"] = [group for group in graph.get("groups", []) if group.get("id") != 70]
    graph["groups"].append({
        "id": 70,
        "title": "LAKIS DETAIL · HighRez → VRAM Gate → Face/Eye → SCOPE",
        "bounding": [-4800, 3560, 1420, 1010],
        "color": "#c23878",
        "flags": {},
    })
    graph["last_node_id"] = max(int(graph.get("last_node_id", 0)), 2203)
    graph["last_link_id"] = max(int(graph.get("last_link_id", 0)), 3798)
    graph.setdefault("extra", {})["lakis_detail_visual_contract"] = {
        "version": 1,
        "route": ["1633", "2202", "2203", "2169", "2170", "2171", "775"],
        "legacy_route": ["1633", "1530", "1836", "1541", "2170", "2171", "775"],
        "mode_switch": 2170,
    }
    serialized = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    TARGET.write_text(serialized, encoding="utf-8")
    RUNTIME_TARGET.write_text(serialized, encoding="utf-8")
    print(f"Built {TARGET} and {RUNTIME_TARGET} "
          f"({len(graph['nodes'])} nodes, {len(graph['links'])} links)")


if __name__ == "__main__":
    main()
