# LAKIS compliance notes

## Built-in wildcards

The seven built-in wildcard files are an original AI-assisted curated dataset created specifically for LAKIS. No third-party wildcard pack, external wildcard collection, or specific external dataset was copied. User-added wildcards are separate user-provided material, and LAKIS does not represent that it owns or has cleared user-supplied content.

## Autocomplete dataset

`autocomplete.csv` is LAKIS-owned original, AI-assisted data created specifically for LAKIS. No external third-party dataset was copied. It requires no third-party permission evidence, `THIRD_PARTY_NOTICES` entry, or separate public user-facing notice.

## External LLLite inpainting weight

`anima-lllite-inpainting-v2.safetensors` is not included, mirrored, or automatically downloaded by LAKIS. Users obtain it directly from the official publisher at `https://huggingface.co/kohya-ss/Anima-LLLite` and install it manually.

The weight is governed by the CircleStone Labs Non-Commercial License v1.0. Its non-commercial and non-production restrictions remain applicable. Known SHA-256: `5242e677d2be34ee70ca7c97c3b14ff5ee49838c03fc1e60ac4852a180db6ef5`.

The `ComfyUI-Anima-LLLite` node code is a separate Apache-2.0 component.

## Translation network disclosure

한국어 번역 기능을 사용하면 번역할 프롬프트 텍스트가 외부 Google 번역 서비스로 전송될 수 있습니다.
