export const $ = (id) => document.getElementById(id);
export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
export function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}
export function button(text, action, className = "secondary") {
  const node = el("button", text, className);
  node.type = "button";
  node.addEventListener("click", async () => {
    node.disabled = true;
    try {
      await action();
    } catch (error) {
      notice(error.message, true);
    } finally {
      node.disabled = false;
    }
  });
  return node;
}
export function field(label, type = "text", value = "", required = true) {
  const wrapper = el("label", label),
    input = el("input");
  input.type = type;
  input.value = value;
  input.required = required;
  wrapper.append(input);
  return [wrapper, input];
}
export function download(value, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = el("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function readImage(file) {
  return new Promise((resolve, reject) => {
    if (
      !["image/png", "image/jpeg", "image/webp"].includes(file.type) ||
      file.size > 10 * 1024 * 1024
    ) {
      reject(new Error("Use PNG, JPEG or WebP files up to 10 MB each."));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Cannot read image"));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error("Invalid image"));
      image.onload = () =>
        resolve({
          image: reader.result,
          pixelWidth: image.naturalWidth,
          pixelHeight: image.naturalHeight,
        });
      image.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}
