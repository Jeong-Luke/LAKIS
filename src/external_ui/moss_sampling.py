"""Schema-bound sampling settings for the integrated MOSS workflow."""

import copy
import math
from moss_errors import MossValidationError
from moss_workflows import get_input, set_input


# Only scalar inputs of the existing graph are exposed. Model paths, links,
# batch size, output paths and the locked i2i path are not overrideable.
EDITABLE = (
    ("1", "모델 로딩", {"weight_dtype": "가중치 데이터 형식"}),
    ("2", "샘플링 Shift", {"shift": "Shift"}),
    ("3", "레이어 가이던스", {
        "double_layers": "Double 레이어",
        "single_layers": "Single 레이어",
        "start_percent": "시작 비율",
        "end_percent": "종료 비율",
    }),
    ("4", "텍스트 인코더", {"device": "실행 장치"}),
)


def inputs_for(schema, class_type):
    inputs = schema.get(class_type, {}).get("input", {})
    return {**inputs.get("required", {}), **inputs.get("optional", {})}


def sampling_choices(schema):
    inputs = inputs_for(schema, "KSampler")
    return {
        key: list(inputs[field][0]) if isinstance(inputs.get(field, [None])[0], (list, tuple)) else []
        for key, field in (("sampler", "sampler_name"), ("scheduler", "scheduler"))
    }


def configuration(schema, graph):
    nodes = []
    for node_id, title, names in EDITABLE:
        node = graph[node_id]
        inputs = inputs_for(schema, node["class_type"])
        fields = []
        for name, label in names.items():
            spec = inputs.get(name)
            if not spec:
                continue
            kind = spec[0]
            bounds = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            field = {"name": name, "label": label, "value": copy.deepcopy(node["inputs"][name])}
            if isinstance(kind, (list, tuple)):
                field.update(type="string", options=list(kind))
            elif kind in ("FLOAT", "INT"):
                field.update(type="number", integer=kind == "INT")
                field.update({key: bounds[key] for key in ("min", "max", "step") if key in bounds})
            elif kind == "STRING":
                field["type"] = "string"
            else:
                continue
            fields.append(field)
        if fields:
            nodes.append({"id": f"moss:{node_id}", "title": title,
                          "class_type": node["class_type"], "fields": fields})
    return {"model": nodes}


def normalize(raw, schema, graph):
    if not isinstance(raw, dict):
        raise MossValidationError("LKS-MOSS-1006", "MOSS 샘플링 설정은 객체여야 합니다.")
    result = {}
    choices = sampling_choices(schema)
    for key, field in (("sampler", "sampler_name"), ("scheduler", "scheduler")):
        value = raw.get(key, get_input(graph, "8", field))
        if not isinstance(value, str) or value not in choices[key]:
            raise MossValidationError(
                "LKS-MOSS-1004" if key == "sampler" else "LKS-MOSS-1005",
                f"MOSS {key} 선택이 현재 ComfyUI 지원 목록에 없습니다.")
        result[key] = value
    overrides = raw.get("node_overrides", {})
    if not isinstance(overrides, dict):
        raise MossValidationError("LKS-MOSS-1006", "MOSS 세부 설정은 객체여야 합니다.")
    allowed = {node["id"]: {field["name"]: field for field in node["fields"]}
               for node in configuration(schema, graph)["model"]}
    normalized = {}
    for node_id, values in overrides.items():
        if node_id not in allowed or not isinstance(values, dict):
            raise MossValidationError("LKS-MOSS-1006", f"지원하지 않는 MOSS 세부 설정입니다: {node_id}")
        normalized[node_id] = {}
        for name, value in values.items():
            field = allowed[node_id].get(name)
            if field is None:
                raise MossValidationError("LKS-MOSS-1006", f"지원하지 않는 MOSS 입력입니다: {name}")
            if field["type"] == "number":
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or (field.get("integer") and type(value) is not int)
                        or ("min" in field and value < field["min"])
                        or ("max" in field and value > field["max"])):
                    raise MossValidationError("LKS-MOSS-1006", f"{field['label']} 값이 허용 숫자 범위를 벗어났습니다.")
            elif not isinstance(value, str):
                raise MossValidationError("LKS-MOSS-1006", f"{field['label']} 값은 문자열이어야 합니다.")
            if "options" in field and value not in field["options"]:
                raise MossValidationError("LKS-MOSS-1006", f"{field['label']} 값이 현재 지원 목록에 없습니다.")
            normalized[node_id][name] = value
    guidance = {**graph["3"]["inputs"], **normalized.get("moss:3", {})}
    if guidance["start_percent"] > guidance["end_percent"]:
        raise MossValidationError("LKS-MOSS-1006", "레이어 가이던스 시작 비율은 종료 비율 이하여야 합니다.")
    result["node_overrides"] = normalized
    return result


def apply(graph, sampling):
    """Apply already validated settings before optional workflow augmentation."""
    set_input(graph, "8", "sampler_name", sampling["sampler"])
    set_input(graph, "8", "scheduler", sampling["scheduler"])
    for node_id, values in sampling["node_overrides"].items():
        graph[node_id.removeprefix("moss:")]["inputs"].update(copy.deepcopy(values))
