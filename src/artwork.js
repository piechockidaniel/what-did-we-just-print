import { api, post } from "./api.js";
import { el, button, field, readImage, notice } from "./ui.js";

export function artworkHistory(variant, refresh, canEdit) {
  const details = el("details"),
    content = el("div");
  details.append(
    el("summary", `Artwork revision ${variant.artworkRevision} / history`),
    content,
  );
  let loaded = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || loaded) return;
    try {
      const versions = await api(`/variants/${variant.id}/artwork`);
      content.replaceChildren();
      for (const version of versions) {
        const entry = el("div", undefined, "work-item"),
          image = el("img");
        image.src = version.image;
        image.alt = `${variant.name}, artwork revision ${version.revision}`;
        image.className = "revision-preview";
        entry.append(
          el(
            "p",
            `Revision ${version.revision} · ${version.readiness} · ${version.actor}`,
          ),
          image,
        );
        content.append(entry);
      }
      loaded = true;
    } catch (error) {
      content.replaceChildren(el("p", error.message));
    }
  });
  if (canEdit) {
    const editor = el("div", undefined, "artwork-revision-editor"),
      fileLabel = el("label", "New artwork revision"),
      file = el("input");
    file.type = "file";
    file.accept = "image/png,image/jpeg,image/webp";
    fileLabel.append(file);
    const [reasonLabel, reason] = field("Reason for artwork change");
    reason.maxLength = 500;
    let incoming, key;
    const preview = el("img");
    preview.hidden = true;
    preview.className = "revision-preview";
    preview.alt = "Proposed artwork revision";
    file.addEventListener("change", async () => {
      try {
        incoming = null;
        preview.hidden = true;
        if (!file.files[0]) return;
        incoming = await readImage(file.files[0]);
        key = crypto.randomUUID();
        preview.src = incoming.image;
        preview.hidden = false;
      } catch (error) {
        notice(error.message, true);
      }
    });
    editor.append(
      el(
        "p",
        "Existing sheets and released work keep their original artwork. A new placement uses this revision; reprints preserve their source revision unless edited.",
      ),
      fileLabel,
      preview,
      reasonLabel,
      button("Save new artwork revision", async () => {
        if (!incoming || !reason.reportValidity())
          throw new Error("Select new artwork and describe the change.");
        await post(`/variants/${variant.id}/artwork`, {
          image: incoming.image,
          expectedRevision: variant.artworkRevision,
          reason: reason.value,
          key,
        });
        await refresh();
        notice(
          "New artwork revision saved. Existing production references were preserved.",
        );
      }),
    );
    details.append(editor);
  }
  return details;
}
