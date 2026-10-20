import { spawn } from "node:child_process";
import { resolve } from "node:path";
const python = resolve(
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill();
  process.exitCode = code;
}
function start(executable, args, environment = {}) {
  const child = spawn(executable, args, {
    stdio: "inherit",
    env: { ...process.env, ...environment },
  });
  children.push(child);
  child.on("error", (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on("exit", (code) => {
    if (!stopping) stop(code || 1);
  });
}
start(
  python,
  ["-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8000"],
  { PRINT_DEV: "1" },
);
start(python, ["-m", "server.worker"]);
start(process.execPath, [resolve("node_modules/vite/bin/vite.js")]);
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
