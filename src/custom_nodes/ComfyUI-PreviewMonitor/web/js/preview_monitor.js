const { app } = window.comfyAPI.app;
const { api } = window.comfyAPI.api;

let _decoding = false;
let _clearBitmapTimer = null;
let _bitmap = null;
let _nodeInfo = { id: null, title: null };

const resetPreview = () => {
    _nodeInfo = { id: null, title: null };
    _decoding = false;

    clearTimeout(_clearBitmapTimer);
    _clearBitmapTimer = setTimeout(() => {
        _bitmap?.close();
        _bitmap = null;
        app.graph.setDirtyCanvas(true, false);
    }, 250);
};

api.addEventListener("execution_success",     resetPreview);
api.addEventListener("execution_error",       resetPreview);
api.addEventListener("execution_interrupted", resetPreview);

api.addEventListener("executing", ({ detail }) => {
    if (!detail) return;
    const node = app.graph.getNodeById(Number(detail.split(":")[0]));
    _nodeInfo = { id: detail, title: node?.subgraph?.name ?? node?.title ?? node?.type ?? null };
    app.graph.setDirtyCanvas(true, false);
});

api.addEventListener("b_preview", async ({ detail }) => {
    if (_decoding) return;
    _decoding = true;
    const newBitmap = await createImageBitmap(detail);
    clearTimeout(_clearBitmapTimer);
    _bitmap?.close();
    _bitmap = newBitmap;
    _decoding = false;
    app.graph.setDirtyCanvas(true, false);
});

app.registerExtension({
    name: "preview_monitor.Preview",
    async registerCustomNodes() {
        class PreviewMonitor extends LiteGraph.LGraphNode {
            static title = "Preview Monitor";
            static category = "utils";

            constructor(title) {
                super(title);
                this.isVirtualNode = true;
                this.size = [240, 260];
                this.resizable = true;
            }
			
			onResize(size) {
				if (size[0] < 240) size[0] = 240;
				if (size[1] < 80) size[1] = 80;
			}

            onDrawBackground(ctx) {
                if (this.flags.collapsed) return;
                const [w, h] = this.size;
                const FOOTER = 20;
                const imgH = h - FOOTER;

                ctx.fillStyle = "#111";
                ctx.fillRect(0, 0, w, imgH);

                if (_bitmap) {
                    const aspect = _bitmap.width / _bitmap.height;
                    let dw = w, dh = w / aspect;
                    if (dh > imgH) { dh = imgH; dw = dh * aspect; }
                    ctx.drawImage(_bitmap, (w - dw) / 2, (imgH - dh) / 2, dw, dh);
                } else {
                    ctx.fillStyle = "#666";
                    ctx.font = "12px monospace";
                    ctx.textAlign = "center";
                    ctx.fillText("waiting for preview...", w / 2, imgH / 2 - 8);
                    ctx.font = "10px monospace";
                    ctx.fillText("(enable preview in Settings > Comfy)", w / 2, imgH / 2 + 8);
                }

                ctx.fillStyle = "#222";
                ctx.fillRect(0, imgH, w, FOOTER);
                ctx.lineWidth = 1;
                ctx.beginPath(); ctx.moveTo(0, imgH); ctx.lineTo(w, imgH); ctx.stroke();

                ctx.font = "10px monospace";
                ctx.fillStyle = "#aaa";
                ctx.textAlign = "right";
                ctx.fillText(_bitmap ? `${_bitmap.width} × ${_bitmap.height}` : "", w - 8, imgH + 13);

                if (_nodeInfo.title) {
                    let label = `▶#${_nodeInfo.id ?? ''}:${_nodeInfo.title}`;
                    ctx.textAlign = "left";
                    while (label.length > 3 && ctx.measureText(label).width > w - 80)
                        label = label.slice(0, -4) + "...";
                    ctx.fillStyle = _nodeInfo.id ? "#7ec8e3" : "#666";
                    ctx.fillText(label, 8, imgH + 13);
                }
            }
        }
        LiteGraph.registerNodeType("PreviewMonitor", PreviewMonitor);
    },
});
