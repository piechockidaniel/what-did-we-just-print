import "./style.css";
import "./workflow.css";
import { api, post } from "./api.js";
import { $, el, notice, button, download, readImage } from "./ui.js";
import { setupWorkflow, renderWorkflow } from "./workflow.js";
import { setupStation, stopCamera } from "./station.js";
import { loadDraft, saveDraft } from "./drafts.js";
import { artworkHistory } from "./artwork.js";

let drafts = [],
  orders = [],
  busy = false,
  pendingOrder;
let userSession;
function persistDraft() {
  const fields = Object.fromEntries(
    ["customer", "order-number", "width", "height"].map((id) => [
      id,
      $(id).value,
    ]),
  );
  return saveDraft({ fields, drafts, pendingOrder }).catch(() =>
    notice(
      "Browser draft recovery is unavailable. Keep this tab open until saving or exporting.",
      true,
    ),
  );
}
const layout = document.querySelector(".layout");
layout.id = "orders-view";
layout.classList.add("view");
document.querySelector(".helper").textContent =
  "SHARED SERVER STORAGE / EXPORT A BACKUP REGULARLY";
document.querySelector(".catalog-note").textContent =
  "REFERENCE ARTWORK / RELEASE A PRODUCTION SHEET BEFORE MATCHING";
const main = document.querySelector("main"),
  nav = el("nav", undefined, "tabs");
nav.setAttribute("aria-label", "Workspace");
for (const [id, title] of [
  ["orders", "Orders & artwork"],
  ["production", "Production"],
  ["station", "Scan station"],
  ["history", "History"],
]) {
  const tab = button(
    title,
    () => {
      document.querySelectorAll(".view").forEach((view) => {
        view.hidden = view.id !== `${id}-view`;
      });
      nav
        .querySelectorAll("button")
        .forEach((item) =>
          item.setAttribute("aria-current", item === tab ? "page" : "false"),
        );
      if (id !== "station") stopCamera();
    },
    "tab",
  );
  tab.setAttribute("aria-current", id === "orders" ? "page" : "false");
  nav.append(tab);
}
layout.before(nav);
const connection = el("p", "Connecting to shared service…", "connection");
connection.id = "connection";
nav.before(connection);
for (const id of ["production", "station", "history"]) {
  const panel = el("section", undefined, "view");
  panel.id = `${id}-view`;
  panel.hidden = true;
  main.append(panel);
}
const tools = el("div", undefined, "toolbar"),
  importFile = el("input");
importFile.type = "file";
importFile.accept = ".json,application/json";
importFile.hidden = true;
tools.append(
  button("Import catalog JSON", () => importFile.click()),
  button("Recover browser catalog", recoverBrowser),
  button("Refresh shared data", refresh),
  importFile,
);
const logout = button("Sign out", async () => {
  await post("/logout", {});
  stopCamera();
  orders = [];
  render();
  renderWorkflow({
    orders: [],
    sheets: [],
    allocations: [],
    history: [],
    jobs: [],
    stations: [],
    user: { role: "operator" },
  });
  window.dispatchEvent(new Event("operator-signed-out"));
  await refresh();
});
logout.hidden = true;
tools.append(logout);
nav.after(tools);
const importPanel = el("section", undefined, "import-panel");
importPanel.hidden = true;
tools.after(importPanel);
importFile.addEventListener("change", async () => {
  try {
    const file = importFile.files[0];
    if (!file) return;
    if (file.size > 80 * 1024 * 1024)
      throw new Error("Catalog exceeds 80 MB. Split into smaller exports.");
    await previewImport(JSON.parse(await file.text()));
  } catch (error) {
    notice(error.message, true);
  } finally {
    importFile.value = "";
  }
});
async function recoverBrowser() {
  const request = indexedDB.open("print-reference-desk", 1);
  request.onupgradeneeded = () =>
    request.result.createObjectStore("orders", { keyPath: "id" });
  const db = await new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    const get = db.transaction("orders").objectStore("orders").getAll();
    const legacy = await new Promise((resolve, reject) => {
      get.onsuccess = () => resolve(get.result);
      get.onerror = () => reject(get.error);
    });
    if (!legacy.length) {
      notice(
        "No legacy catalog at this browser origin. Export from the previous hosted app and import its JSON here.",
      );
      return;
    }
    await previewImport({ schemaVersion: 1, orders: legacy });
  } finally {
    db.close();
  }
}
async function previewImport(catalog) {
  const report = await post("/catalog/preview", catalog);
  importPanel.replaceChildren(el("h2", "IMPORT PREVIEW"));
  for (const item of report)
    importPanel.append(
      el("p", `${item.number}: ${item.status} — ${item.reason}`),
    );
  importPanel.append(
    button("Cancel import", () => {
      importPanel.hidden = true;
    }),
  );
  if (!report.some((item) => item.status === "conflict"))
    importPanel.append(
      button(
        "Confirm import",
        async () => {
          const result = await post("/catalog/import", catalog);
          importPanel.hidden = true;
          await refresh();
          notice(
            `Imported ${result.imported}; skipped ${result.skipped} identical orders. Original browser records were preserved.`,
          );
        },
        "primary",
      ),
    );
  importPanel.hidden = false;
}
function render() {
  const query = $("search").value.toLowerCase(),
    all = orders.flatMap((order) =>
      order.variants.map((variant) => ({ order, variant })),
    );
  $("count").textContent = `${String(all.length).padStart(2, "0")} REFERENCES`;
  const matches = all.filter(({ order, variant }) =>
    [
      order.customer,
      order.orderNumber,
      variant.id,
      variant.name,
      variant.destination,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query),
  );
  const records = $("records");
  records.replaceChildren();
  if (!matches.length) {
    const empty = el("div", undefined, "empty");
    if (!all.length) {
      const sheet = el("div", undefined, "sheet-grid");
      sheet.setAttribute("aria-hidden", "true");
      for (let i = 0; i < 24; i++)
        sheet.append(el("div", i === 0 ? "01" : undefined, "slot"));
      empty.append(sheet);
    }
    empty.append(
      el("h3", all.length ? "NO MATCHING REFERENCES" : "NO ARTWORK YET"),
      el(
        "p",
        all.length
          ? "Try another search."
          : "Upload card fronts or import your catalog.",
      ),
    );
    records.append(empty);
    return;
  }
  const grid = el("div", undefined, "cards");
  for (const { order, variant } of matches) {
    const card = el("article", undefined, "card"),
      preview = el("div", undefined, "preview"),
      image = el("img");
    image.src = variant.image;
    image.alt = `Artwork: ${variant.name}`;
    preview.append(image);
    const details = el("div", undefined, "details");
    details.append(
      el("span", `FEATURES ${variant.status.toUpperCase()}`, "ready"),
      el("h3", variant.name),
      el("div", variant.id, "ref"),
      el("p", `${order.customer} · ${order.orderNumber}`),
      el(
        "p",
        `${order.widthMm} × ${order.heightMm} mm · ${variant.quantity} ordered`,
      ),
      el("p", `Destination: ${variant.destination}`),
    );
    details.append(
      artworkHistory(variant, refresh, userSession?.role !== "operator"),
    );
    card.append(preview, details);
    grid.append(card);
  }
  records.append(grid);
}
function renderDrafts() {
  $("drafts").replaceChildren();
  $("art-status").textContent = drafts.length
    ? `${drafts.length} ARTWORK FILE(S)`
    : "AWAITING ARTWORK";
  drafts.forEach((draft, index) => {
    const box = el("div", undefined, "draft"),
      image = el("img");
    image.src = draft.image;
    image.alt = draft.fileName;
    box.append(image, el("h3", draft.fileName));
    for (const [key, title, type, defaultValue] of [
      [
        "name",
        "Variant / person",
        "text",
        draft.fileName.replace(/\.[^.]+$/, ""),
      ],
      ["quantity", "Quantity", "number", "100"],
      ["destination", "Packing / shipping destination", "text", ""],
    ]) {
      const label = el("label", title),
        input = el("input");
      input.type = type;
      input.required = true;
      input.value = draft[key] ?? defaultValue;
      draft[key] = input.value;
      if (type === "number") {
        input.min = "1";
        input.max = "1000000";
        input.step = "1";
      } else input.maxLength = 250;
      input.addEventListener("input", () => {
        draft[key] = input.value;
        persistDraft();
      });
      label.append(input);
      box.append(label);
    }
    box.append(
      button("Remove artwork", () => {
        drafts.splice(index, 1);
        renderDrafts();
        persistDraft();
      }),
    );
    $("drafts").append(box);
  });
}
async function addImages(files) {
  if (busy) return;
  busy = true;
  $("submit").disabled = true;
  try {
    if (files.length + drafts.length > 50)
      throw new Error("An order can contain up to 50 variants.");
    const incoming = [];
    for (const file of files)
      incoming.push({
        fileName: file.name,
        mimeType: file.type,
        ...(await readImage(file)),
      });
    drafts.push(...incoming);
    renderDrafts();
    await persistDraft();
    notice(
      `${incoming.length} artwork image(s) added. Complete each destination before saving.`,
    );
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy = false;
    $("artwork").value = "";
    $("submit").disabled = false;
  }
}
$("artwork").addEventListener("change", () =>
  addImages([...$("artwork").files]),
);
document.querySelectorAll(".select-artwork").forEach((node) => {
  node.onclick = () => $("artwork").click();
});
const dropZone = $("drop-zone");
for (const name of ["dragenter", "dragover"])
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
for (const name of ["dragleave", "drop"])
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
dropZone.addEventListener("drop", (event) =>
  addImages([...event.dataTransfer.files]),
);
for (const id of ["width", "height"])
  $(id).addEventListener("input", () => {
    $("trim-summary").textContent =
      `${$("width").value} × ${$("height").value} MM`;
  });
$("order-form").addEventListener("input", persistDraft);
$("order-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  if (!drafts.length) {
    notice("Add at least one artwork image.", true);
    return;
  }
  busy = true;
  $("submit").disabled = true;
  try {
    const payload = {
      customer: $("customer").value.trim(),
      orderNumber: $("order-number").value.trim(),
      widthMm: Number($("width").value),
      heightMm: Number($("height").value),
      variants: drafts.map((draft) => ({
        ...draft,
        name: draft.name.trim(),
        quantity: Number(draft.quantity),
        destination: draft.destination.trim(),
      })),
    };
    const fingerprint = JSON.stringify(payload);
    if (pendingOrder?.fingerprint !== fingerprint)
      pendingOrder = {
        fingerprint,
        payload: {
          ...payload,
          id: crypto.randomUUID(),
          variants: payload.variants.map((v) => ({
            ...v,
            id: crypto.randomUUID(),
          })),
        },
      };
    await persistDraft();
    await post("/orders", pendingOrder.payload);
    drafts = [];
    pendingOrder = null;
    $("order-form").reset();
    renderDrafts();
    $("trim-summary").textContent = "90 × 50 MM";
    await saveDraft(null);
    await refresh();
    notice(`Order ${payload.orderNumber} saved to shared storage.`);
  } catch (error) {
    notice(`${error.message} Your draft is retained.`, true);
  } finally {
    busy = false;
    $("submit").disabled = false;
  }
});
$("search").addEventListener("input", render);
$("export").addEventListener("click", async () => {
  try {
    download(
      await api("/catalog/export"),
      `print-scan-catalog-${new Date().toISOString().slice(0, 10)}.json`,
    );
  } catch (error) {
    notice(error.message, true);
  }
});
const signin = el("dialog");
signin.innerHTML =
  '<form id="signin-form"><h2>OPERATOR SIGN IN</h2><label>Name<input name="name" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><p id="signin-error" role="alert"></p><button class="primary">Sign in</button></form>';
document.body.append(signin);
window.addEventListener("signin-required", () => {
  if (!signin.open) signin.showModal();
});
signin.addEventListener("cancel", (event) => event.preventDefault());
$("signin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await post("/login", Object.fromEntries(new FormData(event.target)));
    event.target.reset();
    signin.close();
    await refresh();
  } catch (error) {
    $("signin-error").textContent = error.message;
  }
});
export async function refresh() {
  try {
    const user = await api("/session");
    userSession = user;
    const [catalog, sheets, allocations, history, jobs, stations] =
      await Promise.all([
        api("/orders"),
        api("/sheets"),
        api("/allocations"),
        api("/history"),
        api("/jobs"),
        api("/stations"),
      ]);
    orders = catalog;
    connection.textContent = user.development
      ? "LOCAL DEVELOPMENT · automatic developer identity · server storage"
      : `CONNECTED · ${user.name} · ${user.role}`;
    logout.hidden = user.development;
    connection.classList.remove("offline");
    render();
    renderWorkflow({
      orders,
      sheets,
      allocations,
      history,
      jobs,
      stations,
      user,
    });
  } catch (error) {
    connection.textContent =
      "DISCONNECTED · shared data may be stale · packing requires server confirmation";
    connection.classList.add("offline");
    throw error;
  }
}
setupWorkflow(refresh);
setupStation(refresh);
refresh().catch((error) => notice(error.message, true));
loadDraft()
  .then((saved) => {
    if (!saved || $("customer").value || drafts.length) return;
    for (const [id, value] of Object.entries(saved.fields))
      if ($(id)) $(id).value = value;
    drafts = saved.drafts || [];
    pendingOrder = saved.pendingOrder;
    renderDrafts();
    $("trim-summary").textContent =
      `${$("width").value} × ${$("height").value} MM`;
    if (drafts.length || $("customer").value)
      notice(
        "Recovered your unsaved browser draft. Shared production quantities still come from the server.",
      );
  })
  .catch(() =>
    notice(
      "Browser draft recovery is unavailable. Shared server storage remains available.",
      true,
    ),
  );
