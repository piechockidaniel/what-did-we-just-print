import { api, post } from "./api.js";
import { $, el, button, field, notice } from "./ui.js";

let refresh,
  state = { orders: [], sheets: [], allocations: [] },
  editingSheetId = null;
export const getState = () => state;
export function setupWorkflow(callback) {
  refresh = callback;
}

function submitForm(form, action) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      await action();
    } catch (error) {
      notice(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
}
function submit(text) {
  const node = el("button", text, "primary");
  node.type = "submit";
  return node;
}

export function packingForm(allocation, scanId, callback = refresh) {
  const form = el("form", undefined, "packing-form");
  const [quantityLabel, quantity] = field("Quantity to pack", "number", "1");
  quantity.min = "1";
  quantity.max = allocation.remaining;
  quantity.step = "1";
  const [reasonLabel, reason] = field(
    "Confirmation / production context",
    "text",
    "",
  );
  reason.maxLength = 500;
  const key = crypto.randomUUID();
  form.append(
    quantityLabel,
    reasonLabel,
    submit(scanId ? "Confirm packed quantity" : "Record manual packing"),
  );
  submitForm(form, async () => {
    await post(`/allocations/${allocation.id}/pack`, {
      key,
      quantity: Number(quantity.value),
      revision: allocation.revision,
      scanId,
      reason: reason.value,
    });
    notice("Packing committed. Remaining work refreshed from the server.");
    await callback();
  });
  return form;
}

function reasonAction(title, action) {
  const form = el("form", undefined, "reason-form");
  const [label, input] = field("Reason", "text");
  input.maxLength = 500;
  form.append(label, submit(title));
  const key = crypto.randomUUID();
  submitForm(form, () => action({ key, reason: input.value }));
  return form;
}

function sheetEditor(initial = null) {
  const section = el("section", undefined, "surface");
  section.append(
    el(
      "h2",
      initial ? `EDIT DRAFT: ${initial.number}` : "REGISTER A PRODUCTION SHEET",
    ),
  );
  const form = el("form");
  const fields = [
    ["Sheet number", "text", initial?.number ?? ""],
    ["Sheet width (mm)", "number", initial?.width ?? "320"],
    ["Sheet height (mm)", "number", initial?.height ?? "450"],
    ["Impressions", "number", initial?.impressions ?? "100"],
  ].map((args) => field(...args));
  fields.forEach(([label, input], index) => {
    if (index) {
      input.min = "1";
      input.max = index === 3 ? "1000000" : "3000";
      input.step = "1";
    }
    form.append(label);
  });
  const variants = state.orders.flatMap((order) =>
    order.variants.map((variant) => ({ ...variant, order })),
  );
  const label = el("label", "Artwork variant"),
    select = el("select");
  const emptyOption = el("option", "Select artwork");
  emptyOption.value = "";
  select.append(emptyOption);
  for (const variant of variants) {
    const option = el(
      "option",
      `${variant.order.orderNumber} / ${variant.name} · ${variant.order.widthMm} × ${variant.order.heightMm} mm`,
    );
    option.value = variant.id;
    select.append(option);
  }
  label.append(select);
  form.append(label);
  const versionLabel = el("label", "Artwork revision"),
    versionSelect = el("select");
  versionLabel.append(versionSelect);
  form.append(versionLabel);
  versionSelect.disabled = true;
  const versionImages = { ...initial?.artworkImages },
    latestVersions = new Map();
  let versionRequest = 0,
    addPlacement;
  select.addEventListener("change", async () => {
    const request = ++versionRequest;
    versionSelect.replaceChildren();
    versionSelect.disabled = true;
    addPlacement.disabled = true;
    try {
      if (!select.value) return;
      const history = await api(`/variants/${select.value}/artwork`);
      if (request !== versionRequest) return;
      for (const version of history) {
        const option = el(
          "option",
          `Revision ${version.revision}${version === history[0] ? " (current)" : " (historical)"}`,
        );
        option.value = version.id;
        versionSelect.append(option);
        versionImages[version.id] = version.image;
      }
      latestVersions.set(select.value, history[0].id);
      versionSelect.disabled = false;
    } catch (error) {
      notice(error.message, true);
    } finally {
      if (request === versionRequest)
        addPlacement.disabled = !versionSelect.value;
    }
  });
  const [xLabel, x] = field("X position (mm)", "number", "0", false),
    [yLabel, y] = field("Y position (mm)", "number", "0", false);
  x.min = y.min = "0";
  x.step = y.step = ".1";
  const rotationLabel = el("label", "Rotation"),
    rotation = el("select");
  for (const angle of [0, 90, 180, 270]) {
    const option = el("option", `${angle}°`);
    option.value = angle;
    rotation.append(option);
  }
  rotationLabel.append(rotation);
  form.append(xLabel, yLabel, rotationLabel);
  const placements = structuredClone(initial?.placements ?? []),
    placementList = el("div", undefined, "placement-list"),
    preview = el("div", undefined, "composition");
  const redraw = () => {
    placementList.replaceChildren();
    preview.replaceChildren();
    preview.style.aspectRatio = `${Number(fields[1][1].value) || 320} / ${Number(fields[2][1].value) || 450}`;
    placements.forEach((p, index) => {
      const variant = variants.find((v) => v.id === p.variantId),
        item = el("div", undefined, "placement-row");
      item.append(
        el(
          "span",
          `${variant.name} · ${p.x}, ${p.y} mm · ${p.rotation}° · ${p.side}${p.artworkVersionId !== (latestVersions.get(variant.id) ?? variant.artworkVersionId) ? " · older artwork revision" : " · current artwork"}`,
        ),
        button("Remove", () => {
          placements.splice(index, 1);
          redraw();
        }),
      );
      placementList.append(item);
      const image = el("img");
      image.src = versionImages[p.artworkVersionId] ?? variant.image;
      image.alt = variant.name;
      const rotated = [90, 270].includes(p.rotation),
        width = rotated ? variant.order.heightMm : variant.order.widthMm,
        height = rotated ? variant.order.widthMm : variant.order.heightMm;
      const placement = el("div", undefined, "composition-placement");
      placement.style.left = `${(100 * p.x) / Number(fields[1][1].value)}%`;
      placement.style.top = `${(100 * p.y) / Number(fields[2][1].value)}%`;
      placement.style.width = `${(100 * width) / Number(fields[1][1].value)}%`;
      placement.style.height = `${(100 * height) / Number(fields[2][1].value)}%`;
      image.style.left = image.style.top = "50%";
      image.style.width = rotated ? `${(100 * height) / width}%` : "100%";
      image.style.height = rotated ? `${(100 * width) / height}%` : "100%";
      image.style.transform = `translate(-50%, -50%) rotate(${p.rotation}deg)`;
      image.title = `${variant.name}, ${p.rotation} degrees (placement bounds)`;
      placement.append(image);
      preview.append(placement);
    });
  };
  fields
    .slice(1, 3)
    .forEach(([, input]) => input.addEventListener("input", redraw));
  addPlacement = button("Add placement", () => {
    const variant = variants.find((v) => v.id === select.value);
    if (!variant) throw new Error("Select a variant first.");
    if (
      !Number.isFinite(Number(x.value)) ||
      !Number.isFinite(Number(y.value)) ||
      Number(x.value) < 0 ||
      Number(y.value) < 0
    )
      throw new Error("Enter nonnegative placement coordinates.");
    placements.push({
      variantId: select.value,
      x: Number(x.value),
      y: Number(y.value),
      rotation: Number(rotation.value),
      side: variant.side,
      artworkVersionId: versionSelect.value || variant.artworkVersionId,
    });
    redraw();
  });
  addPlacement.disabled = true;
  form.append(
    addPlacement,
    placementList,
    preview,
    el(
      "p",
      "Preview shows placement bounds. Release quantity = impressions × placements per variant. Front/back linked product workflows need a confirmed upstream schema.",
      "helper",
    ),
    submit(initial ? "Save draft changes" : "Save draft sheet"),
  );
  const saveKey = crypto.randomUUID();
  submitForm(form, async () => {
    const body = {
      number: fields[0][1].value,
      widthMm: Number(fields[1][1].value),
      heightMm: Number(fields[2][1].value),
      impressions: Number(fields[3][1].value),
      placements,
    };
    if (initial)
      await api(`/sheets/${initial.id}`, {
        method: "PUT",
        body: { ...body, key: saveKey, expectedRevision: initial.revision },
      });
    else await post("/sheets", body);
    editingSheetId = null;
    await refresh();
    notice("Draft sheet saved. Check quantities before release.");
  });
  section.append(form);
  if (initial)
    section.append(
      button("Cancel editing", () => {
        editingSheetId = null;
        renderWorkflow(state);
      }),
    );
  const jsonInput = el("input");
  jsonInput.type = "file";
  jsonInput.accept = ".json";
  jsonInput.hidden = true;
  const importPreview = el("div");
  jsonInput.addEventListener("change", async () => {
    try {
      const file = jsonInput.files[0];
      if (!file) return;
      if (file.size > 1024 * 1024)
        throw new Error("Sheet JSON must be under 1 MB.");
      const sheet = JSON.parse(await file.text());
      importPreview.replaceChildren(
        el(
          "p",
          `Sheet ${sheet.number}: ${sheet.placements?.length ?? 0} placements; ${sheet.impressions} impressions. Server validates bounds and overlaps.`,
        ),
        button("Confirm sheet import", async () => {
          await post("/sheets", sheet);
          await refresh();
          notice("Imported draft sheet.");
        }),
      );
    } catch (error) {
      notice(error.message, true);
    } finally {
      jsonInput.value = "";
    }
  });
  section.append(
    button("Import sheet JSON", () => jsonInput.click()),
    jsonInput,
    importPreview,
  );
  redraw();
  return section;
}

export function renderWorkflow(next) {
  state = next;
  const production = $("production-view");
  production.replaceChildren();
  const active = state.allocations.filter((row) => row.remaining > 0);
  const summary = el("div", undefined, "metrics");
  for (const [name, value] of [
    ["Active allocations", active.length],
    ["Units remaining", active.reduce((sum, row) => sum + row.remaining, 0)],
    ["Sheets", state.sheets.length],
  ]) {
    const metric = el("div");
    metric.append(el("strong", String(value)), el("span", name));
    summary.append(metric);
  }
  production.append(summary);
  const columns = el("div", undefined, "workflow-columns"),
    list = el("section", undefined, "surface");
  list.append(el("h2", "PRODUCTION SHEETS"));
  for (const sheet of state.sheets) {
    const item = el("article", undefined, "work-item");
    const rows = state.allocations.filter((a) => a.sheet_id === sheet.id);
    const complete =
      sheet.state === "released" &&
      rows.length &&
      rows.every((a) => a.remaining === 0);
    item.append(
      el("h3", sheet.number),
      el(
        "p",
        `${sheet.width} × ${sheet.height} mm · ${sheet.impressions} impressions · ${sheet.placements.length} placements`,
      ),
      el(
        "span",
        complete ? "COMPLETE / RECONCILED" : sheet.state.toUpperCase(),
        "ready",
      ),
    );
    if (sheet.state === "draft") {
      const key = crypto.randomUUID();
      const releaseButton = button("Release to production", async () => {
        await post(`/sheets/${sheet.id}/release`, {
          key,
          expectedRevision: sheet.revision,
        });
        await refresh();
        notice(
          "Sheet released. Allocations are active; feature readiness is shown separately.",
        );
      });
      releaseButton.disabled = editingSheetId === sheet.id;
      if (releaseButton.disabled)
        releaseButton.title = "Save or cancel draft edits before release";
      item.append(
        el(
          "p",
          "Release creates active quantities. A reprint is a new sheet with a new number.",
        ),
        button("Edit draft", () => {
          editingSheetId = sheet.id;
          renderWorkflow(state);
        }),
        releaseButton,
      );
    } else
      item.append(
        button("Prepare reprint draft", async () => {
          await post("/sheets", {
            number: `${sheet.number}-REPRINT-${Date.now()}`,
            widthMm: sheet.width,
            heightMm: sheet.height,
            impressions: sheet.impressions,
            placements: sheet.placements,
          });
          await refresh();
          notice(
            "Reprint draft created with the original composition and quantities. Review before release.",
          );
        }),
      );
    list.append(item);
  }
  if (!state.sheets.length)
    list.append(
      el(
        "p",
        "No sheets yet. Register artwork, then place variants on a sheet.",
      ),
    );
  const initial = state.sheets.find(
    (sheet) => sheet.id === editingSheetId && sheet.state === "draft",
  );
  if (!initial) editingSheetId = null;
  columns.append(sheetEditor(initial), list);
  production.append(columns);
  const queue = el("section", undefined, "surface");
  queue.append(el("h2", "ACTIVE PRODUCTION & PACKING"));
  queue.append(
    el(
      "p",
      "Manual packing requires independent identification. Scan review and quantity confirmation are separate actions.",
    ),
  );
  for (const allocation of active) {
    const item = el("article", undefined, "work-item");
    item.append(
      el("h3", `${allocation.orderNumber} / ${allocation.name}`),
      el(
        "p",
        `Sheet ${allocation.sheetNumber} · Destination: ${allocation.destination}`,
      ),
      el(
        "p",
        `${allocation.packed} packed / ${allocation.released} released · ${allocation.remaining} remaining · ${allocation.cancelled} cancelled · revision ${allocation.revision}`,
      ),
      el(
        "span",
        `ARTWORK REVISION ${allocation.artworkRevision} · FEATURES ${allocation.readiness.toUpperCase()}`,
        "ready",
      ),
    );
    const details = el("details"),
      packingTitle = el("summary", "Record manually identified packing");
    details.append(packingTitle, packingForm(allocation, null));
    item.append(details);
    if (state.user.role !== "operator") {
      const cancel = el("details");
      cancel.append(
        el("summary", "Cancel remaining work"),
        reasonAction("Cancel remaining quantity", async (payload) => {
          await post(`/allocations/${allocation.id}/cancel`, payload);
          await refresh();
          notice("Remaining quantity cancelled with audit history.");
        }),
      );
      item.append(cancel);
    }
    queue.append(item);
  }
  if (!active.length)
    queue.append(el("p", "No active allocations. Release a sheet to begin."));
  production.append(queue);
  const jobs = el("section", undefined, "surface");
  jobs.append(el("h2", "REFERENCE PREPARATION"));
  for (const job of state.jobs) {
    const row = el("div", undefined, "work-item");
    row.append(
      el(
        "p",
        `${job.artwork_id.slice(0, 12)} · ${job.state} · attempts ${job.attempts}${job.error ? ` · ${job.error}` : ""}`,
      ),
    );
    if (job.state === "failed" && state.user.role !== "operator")
      row.append(
        button("Retry preparation", async () => {
          await post(`/jobs/${job.id}/retry`, {
            key: crypto.randomUUID(),
            reason: "Operator requested preparation retry",
          });
          await refresh();
        }),
      );
    jobs.append(row);
  }
  production.append(jobs);
  renderHistory(state.history);
  window.dispatchEvent(
    new CustomEvent("production-updated", { detail: state }),
  );
}

function renderHistory(items) {
  const panel = $("history-view");
  panel.replaceChildren(el("h2", "PRODUCTION AUDIT HISTORY"));
  const list = el("div"),
    reversed = new Set(
      items
        .filter((e) => e.kind === "packing.reversed")
        .map((e) => e.entity_id),
    );
  function append(events) {
    for (const event of events) {
      const card = el("article", undefined, "work-item");
      card.append(
        el("h3", event.kind),
        el("p", `${new Date(event.created).toLocaleString()} · ${event.actor}`),
        el("p", event.entity_id, "ref"),
      );
      const detail = el("details");
      detail.append(
        el("summary", "Event details"),
        el("pre", JSON.stringify(event.payload, null, 2)),
      );
      card.append(detail);
      if (
        event.kind === "allocation.packed" &&
        !reversed.has(event.id) &&
        state.user.role !== "operator"
      )
        card.append(
          reasonAction("Reverse this packing event", async (payload) => {
            await post(`/packing/${event.id}/reverse`, payload);
            await refresh();
            notice(
              "Packing reversal recorded. Allocation reopened where applicable.",
            );
          }),
        );
      list.append(card);
    }
  }
  append(items);
  panel.append(list);
  let offset = items.length;
  panel.append(
    button("Load older events", async () => {
      const older = await api(`/history?offset=${offset}`);
      offset += older.length;
      append(older);
      if (!older.length) notice("All history loaded.");
    }),
  );
}
