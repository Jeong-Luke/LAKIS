const fs = require("fs");

const workflowPath = process.argv[2];
if (!workflowPath) throw new Error("workflow path is required");
const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));

function expandAndLayout(graph) {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  if (!nodes.length) return;
  for (const node of nodes) {
    node.flags = { ...(node.flags || {}), collapsed: false };
    const size = Array.isArray(node.size) ? node.size : [280, 120];
    node.size = [Math.max(260, Number(size[0]) || 280), Math.max(80, Number(size[1]) || 120)];
  }

  const xs = nodes.map(node => Number(node.pos?.[0]) || 0);
  const minX = Math.min(...xs);
  const columns = new Map();
  for (const node of nodes) {
    const originalX = Number(node.pos?.[0]) || 0;
    const column = Math.round((originalX - minX) / 430);
    if (!columns.has(column)) columns.set(column, []);
    columns.get(column).push(node);
  }

  const orderedColumns = [...columns.keys()].sort((a, b) => a - b);
  orderedColumns.forEach((column, visualColumn) => {
    const columnNodes = columns.get(column).sort((a, b) =>
      (Number(a.pos?.[1]) || 0) - (Number(b.pos?.[1]) || 0));
    let y = 0;
    for (const node of columnNodes) {
      node.pos = [visualColumn * 430, y];
      y += node.size[1] + 70;
    }
  });

  // Old annotation boxes belonged to the compact authoring layout and would
  // otherwise cover nodes after the diagnostic expansion.
  graph.groups = [];
}

expandAndLayout(workflow);
for (const subgraph of workflow.definitions?.subgraphs || []) expandAndLayout(subgraph);
workflow.extra = workflow.extra || {};
workflow.extra.ds = { scale: 0.28, offset: [120, 120] };
workflow.extra.lakis_runtime_visual_layout = {
  mode: "fully-expanded-diagnostic",
  generated_at: new Date().toISOString(),
};

fs.writeFileSync(workflowPath, JSON.stringify(workflow), "utf8");
