import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const RUFF_BIN = "/home/lenny/myp/tuppo/v/bin/ruff";

export default function (pi: ExtensionAPI) {
  // Track Python files modified in the current agent run
  let modifiedPythonFiles: string[] = [];

  pi.on("session_start", async (_event, ctx) => {
    ctx.ui.setStatus("ruff", "ruff: ready");
  });

  // Collect Python files being written or edited
  pi.on("tool_call", async (event, _ctx) => {
    if (event.toolName === "write" || event.toolName === "edit") {
      const path = (event as any).input?.path;
      if (typeof path === "string" && path.endsWith(".py")) {
        modifiedPythonFiles.push(path);
      }
    }
  });

  // At end of the agent loop (after all turns), run ruff once on all modified Python files
  pi.on("agent_end", async (_event, ctx) => {
    if (modifiedPythonFiles.length === 0) {
      modifiedPythonFiles = [];
      return;
    }

    const files = [...modifiedPythonFiles];
    modifiedPythonFiles = [];

    try {
      const result = await pi.exec(RUFF_BIN, ["check", "--output-format=concise", ...files], {
        timeout: 30000,
      });

      if (result.code !== 0 && result.stdout.trim()) {
        // Ruff found issues — send as a follow-up so the LLM fixes them
        pi.sendUserMessage(
          `Ruff found linting issues in the files you just modified. Please fix them:\n\n${result.stdout.trim()}`,
          { deliverAs: "followUp" }
        );
        ctx.ui.setStatus("ruff", "ruff: issues found, fixing...");
      } else {
        ctx.ui.setStatus("ruff", "ruff: clean");
      }
    } catch (err: any) {
      ctx.ui.setStatus("ruff", `ruff: error (${err.message ?? "unknown"})`);
    }
  });
}
