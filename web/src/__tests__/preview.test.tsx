import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntryForm } from "../components/EntryForm";
import { previewLine, previewPages } from "../pages";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("preview arithmetic (inclusive, DECISIONS.md 1.1)", () => {
  it("counts 43-43 as one page", () => {
    expect(previewPages(43, 43)).toBe(1);
    expect(previewLine("43", "43")).toBe("that's 1 page");
  });

  it("counts 43-71 as twenty-nine pages", () => {
    expect(previewPages(43, 71)).toBe(29);
    expect(previewLine("43", "71")).toBe("that's 29 pages");
  });

  it("shows nothing until both inputs are numbers and end >= start", () => {
    expect(previewLine("43", "")).toBeNull();
    expect(previewLine("", "71")).toBeNull();
    expect(previewLine("43", "12")).toBeNull();
    expect(previewLine("43", "seventy")).toBeNull();
  });
});

describe("the live preview line", () => {
  async function type(start: string, end: string) {
    const user = userEvent.setup();
    render(
      <EntryForm
        onSaved={async () => {}}
        onUnreachable={() => {}}
        classes={[]}
        entries={[]}
      />,
    );
    if (start) await user.type(screen.getByLabelText("Start page"), start);
    if (end) await user.type(screen.getByLabelText("End page"), end);
    return user;
  }

  it("renders 'that's 29 pages' for 43 to 71", async () => {
    await type("43", "71");
    expect(screen.getByText("that's 29 pages")).toBeInTheDocument();
  });

  it("renders 'that's 1 page' for 43 to 43", async () => {
    await type("43", "43");
    expect(screen.getByText("that's 1 page")).toBeInTheDocument();
  });

  it("stays empty while only one box is filled", async () => {
    await type("43", "");
    expect(screen.queryByText(/that's/)).not.toBeInTheDocument();
  });
});
