"""Stable MOSS diagnostics, separate from ANIMA's node identifiers."""

MESSAGES = {
    "LKS-MOSS-1001": "MOSS 실행에 필요한 ComfyUI 기능이 없어요. 업데이트·복구 후 다시 실행해 주세요.",
    "LKS-MOSS-1002": "MOSS 모델·VAE·CLIP을 확인해 주세요. 설치가 끝난 모델을 다시 선택해 주세요.",
    "LKS-MOSS-1003": "MOSS LoRA 설정이 올바르지 않아요. 전용 LoRA를 다시 선택하거나 해제해 주세요.",
    "LKS-MOSS-1004": "현재 MOSS 런타임이 지원하는 샘플러를 선택해 주세요.",
    "LKS-MOSS-1005": "현재 MOSS 런타임이 지원하는 스케줄러를 선택해 주세요.",
    "LKS-MOSS-1006": "MOSS 세부 설정이 올바르지 않아요. Shift·가이던스·로딩 설정을 확인해 주세요.",
    "LKS-MOSS-1007": "MOSS 영역 프롬프트의 개수·좌표·문구를 확인해 주세요.",
    "LKS-MOSS-1008": "현재 MOSS에서 잠긴 기능이 요청됐어요. i2i·포즈·인페인트·디테일 기능을 꺼 주세요.",
    "LKS-MOSS-1009": "MOSS 생성 설정을 확인해 주세요. 해상도·시드·CFG·프롬프트가 올바르지 않아요.",
    "LKS-MOSS-1010": "MOSS 공식 워크플로를 읽지 못했어요. 업데이트·복구 후 다시 실행해 주세요.",
    "LKS-MOSS-1011": "ComfyUI가 MOSS 요청 입력을 거부했어요. 오류 정보의 노드와 입력값을 확인해 주세요.",
    "LKS-MOSS-1101": "MOSS 생성 모델을 불러오지 못했어요. 모델 파일과 GPU 메모리를 확인해 주세요.",
    "LKS-MOSS-1102": "MOSS 텍스트 인코더를 불러오지 못했어요. Qwen3.5 인코더를 확인해 주세요.",
    "LKS-MOSS-1103": "MOSS VAE를 불러오지 못했어요. FLUX.2 VAE를 확인해 주세요.",
    "LKS-MOSS-1201": "MOSS 프롬프트를 인코딩하지 못했어요. 프롬프트·영역·인코더를 확인해 주세요.",
    "LKS-MOSS-1202": "MOSS 샘플링 중 오류가 발생했어요. 샘플러·스케줄러·CFG를 확인해 주세요.",
    "LKS-MOSS-1203": "MOSS 이미지를 디코딩하지 못했어요. VAE와 해상도를 확인해 주세요.",
    "LKS-MOSS-1204": "MOSS 이미지를 저장하지 못했어요. 저장 경로·권한·공간을 확인해 주세요.",
    "LKS-MOSS-1205": "MOSS LoRA를 적용하지 못했어요. LoRA의 호환성과 강도를 확인해 주세요.",
    "LKS-MOSS-1206": "MOSS Shift·레이어 가이던스를 적용하지 못했어요. 세부 설정을 확인해 주세요.",
    "LKS-MOSS-1207": "MOSS 초기 잠재 이미지를 만들지 못했어요. 해상도를 확인해 주세요.",
    "LKS-MOSS-1208": "MOSS 저장 응답에서 결과 파일을 찾지 못했어요. 오류 정보를 복사해 주세요.",
    "LKS-MOSS-1901": "MOSS 생성 중 오류가 발생했어요. 오류 정보를 복사해 전달해 주세요.",
}

NODE_CODES = {
    "UNETLoader": "LKS-MOSS-1101",
    "UNet loader with Name (Image Saver)": "LKS-MOSS-1101",
    "CLIPLoader": "LKS-MOSS-1102",
    "VAELoader": "LKS-MOSS-1103",
    "CLIPTextEncode": "LKS-MOSS-1201",
    "KSampler": "LKS-MOSS-1202",
    "Sampler Selector (Image Saver)": "LKS-MOSS-1202",
    "Scheduler Selector (Image Saver)": "LKS-MOSS-1202",
    "VAEDecode": "LKS-MOSS-1203",
    "Image Saver": "LKS-MOSS-1204",
    "LoraLoaderModelOnly": "LKS-MOSS-1205",
    "ModelSamplingAuraFlow": "LKS-MOSS-1206",
    "SkipLayerGuidanceDiTSimple": "LKS-MOSS-1206",
    "EmptyFlux2LatentImage": "LKS-MOSS-1207",
}


def public_error(code):
    return code, MESSAGES[code]


class MossValidationError(ValueError):
    failure_stage = "MOSS 요청 검증"

    def __init__(self, code, detail):
        self.code, self.public_message = public_error(code)
        super().__init__(detail)

    def diagnostic(self):
        return {"generation_engine": "moss", "validation_code": self.code}
