// SPDX-License-Identifier: GPL-3.0-only
// Reuse the upstream clipped masks; only exposed painted pixels need a prompt.
export function findMissingPaintPrompt(painter) {
  const rendered = painter.layerMasks.render();
  const uncovered = new Float32Array(painter.width * painter.height).fill(1);
  for (let index = painter.layers.length - 1; index >= 0; index--) {
    const layer = painter.layers[index];
    if (!layer.visible) continue;
    const pixels = rendered.get(layer).canvas.getContext("2d")
      .getImageData(0, 0, painter.width, painter.height).data;
    let painted = false;
    for (let pixel = 0; pixel < uncovered.length; pixel++) {
      const alpha = pixels[pixel * 4 + 3] / 255;
      if (alpha * uncovered[pixel] > 0) painted = true;
      uncovered[pixel] *= 1 - alpha;
    }
    if (painted && !layer.prompt.trim()) return { layer, index };
  }
  return null;
}
