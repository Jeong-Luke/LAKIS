# SPDX-FileCopyrightText: 2026 灰暗x
# SPDX-FileCopyrightText: 2026 ComfyUI-KR-Camera-Control contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from .camera_control import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, VERSION

__version__ = VERSION

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]
