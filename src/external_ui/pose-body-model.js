// SPDX-License-Identifier: GPL-3.0-only
// Bundled male/female MHR models share the same named rig and bind transforms.
async function loadAppearance(editor, snapshot) {
  const next = structuredClone(snapshot);
  const records = Array.isArray(next.bodies) ? next.bodies : [next];
  const enabled = records.map(record => record.ik.map(chain => chain.enabled));
  // An appearance-only reload must not solve the user's joint pose again.
  for (const record of records) for (const chain of record.ik) chain.enabled = false;
  await editor.load(next);
  editor.bodies.forEach((body, index) => {
    body.chains.forEach((chain, joint) => { chain.enabled = enabled[index][joint]; });
  });
}

export async function applyBodyModel(editor, gender, femaleShape, femaleColor = "#f4b6c2") {
  const body = editor.selectedBody;
  if (!body) return;
  if (body.source !== "MHR") throw Error("남성·여성 모델 선택은 MHR 인물에서 지원합니다.");
  editor.record();
  const original = editor.snapshot(), next = structuredClone(original);
  const record = Array.isArray(next.bodies)
    ? next.bodies.find(item => item.id === body.id) : next;
  record.body = gender;
  if (gender === "female") {
    record.shape = structuredClone(femaleShape);
    record.body_color = femaleColor;
  }
  else delete record.shape;
  const history = editor.history.slice(), future = editor.future.slice();
  try {
    await loadAppearance(editor, next);
  } catch (error) {
    await loadAppearance(editor, original);
    editor.history = history;
    editor.future = future;
    throw error;
  }
  editor.history = history;
  editor.commit();
  editor.record();
}
