# ComfyUI-PreviewMonitor

<img width="1678" height="748" alt="SHANA Anima-Sample-260516 - ComfyUI - Chrome 2026-05-18 19-48-08 (1)" src="https://github.com/user-attachments/assets/f9eb0314-d275-46a0-8c8d-a607eeb9581e" />

A frontend-only node that displays the live sampling preview of the currently executing node.

## Features

- Displays real-time KSampler step previews as they are generated
- Shows the current executing node name and ID in the status bar

## Requirements

Preview must be enabled in ComfyUI settings:
**Settings → Comfy → Preview Method** → set to `taesd`, `latent2rgb`, or `auto`


## Usage

Add the node from the node menu: `__frontend_only__ → PreviewMonitor`

No inputs or outputs. Place it anywhere in your workflow.
