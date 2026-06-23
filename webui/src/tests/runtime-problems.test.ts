import { describe, expect, it } from "vitest";

import { collectRuntimeProblems } from "@/lib/runtime-problems";
import type { UIMessage } from "@/lib/types";

describe("collectRuntimeProblems", () => {
  it("extracts file-linked pytest failures from tool events", () => {
    const messages: UIMessage[] = [{
      id: "trace-1",
      role: "tool",
      kind: "trace",
      content: "",
      traces: [],
      createdAt: 1,
      toolEvents: [{
        phase: "error",
        call_id: "call-cli",
        name: "run_cli_app",
        arguments: { name: "pytest", args: ["-q"] },
        error: "FAILED tests/test_editor.py::test_render - AssertionError\n/workspace/tests/test_editor.py:42: AssertionError",
      }],
    }];

    const problems = collectRuntimeProblems(messages, "/workspace");

    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({
      source: "runtime-pytest",
      display_path: "tests/test_editor.py",
      line: 42,
      column: 1,
    });
    expect(problems[0]?.path).toBe("/workspace/tests/test_editor.py:42:1");
  });

  it("extracts python traceback locations for generic tool failures", () => {
    const messages: UIMessage[] = [{
      id: "trace-2",
      role: "tool",
      kind: "trace",
      content: "",
      traces: [],
      createdAt: 2,
      toolEvents: [{
        phase: "error",
        call_id: "call-tool",
        name: "run_command",
        arguments: { command: "python app.py" },
        error: "Traceback (most recent call last):\n  File \"/workspace/src/app.py\", line 17, in <module>\n    raise ValueError('boom')\nValueError: boom",
      }],
    }];

    const problems = collectRuntimeProblems(messages, "/workspace");

    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({
      source: "runtime-run_command",
      display_path: "src/app.py",
      line: 17,
      column: 1,
    });
  });
});
