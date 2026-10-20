import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
const executable = resolve(
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const result = spawnSync(executable, process.argv.slice(2), {
  stdio: "inherit",
});
if (result.error)
  console.error(
    "Create .venv and install requirements.txt first:",
    result.error.message,
  );
process.exit(result.status ?? 1);
