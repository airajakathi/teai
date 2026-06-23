import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkillsCatalogSettings } from "@/components/settings/SkillsCatalogSettings";
import { ClientProvider } from "@/providers/ClientProvider";

describe("SkillsCatalogSettings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the tool catalog and opens tool schema details", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url === "/api/webui/tools") {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            tools: [
              {
                name: "read_file",
                description: "Read a file from the local filesystem.",
                source: "builtin",
                read_only: true,
                concurrency_safe: true,
                exclusive: false,
                parameters: {
                  type: "object",
                  properties: {
                    file_path: {
                      type: "string",
                      description: "Absolute path to the file.",
                    },
                  },
                  required: ["file_path"],
                },
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <ClientProvider client={{} as never} token="tok">
        <SkillsCatalogSettings
          skills={[
            {
              name: "github",
              description: "GitHub helper",
              source: "builtin",
              available: true,
            },
          ]}
        />
      </ClientProvider>,
    );

    expect(await screen.findByText("Agent tools")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Open details for tool read_file" }));

    expect(await screen.findAllByText("Read-only")).not.toHaveLength(0);
    expect(screen.getByText("file_path")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("shows a skill load failure instead of a false empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ tools: [] }),
      })) as typeof fetch,
    );

    render(
      <ClientProvider client={{} as never} token="tok">
        <SkillsCatalogSettings skills={[]} skillsLoading={false} skillsLoadFailed />
      </ClientProvider>,
    );

    expect(await screen.findByText("Could not load the skill catalog.")).toBeInTheDocument();
    expect(screen.queryByText("No skills are available.")).not.toBeInTheDocument();
  });
});
