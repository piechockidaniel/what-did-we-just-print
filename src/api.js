export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Print-Client": "web",
        ...options.headers,
      },
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new Error(
      "Server disconnected. Your draft is retained; no success is assumed.",
    );
  }
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("signin-required"));
    const message = Array.isArray(result?.detail)
      ? result.detail
          .map((item) => `${item.loc.join(".")}: ${item.msg}`)
          .join("; ")
      : result?.detail;
    throw new Error(
      message ||
        `Service unavailable (${response.status}). Check the API terminal.`,
    );
  }
  return result;
}
export const post = (path, body) => api(path, { method: "POST", body });
