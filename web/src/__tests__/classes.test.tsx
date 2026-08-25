import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { defaultClassId } from "../classes";
import { suggestColor } from "../palette";
import {
  ENTRY,
  classWith,
  entryWith,
  installPalette,
  removePalette,
  statsWith,
  stubFetch,
} from "./helpers";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  removePalette();
});

const BIO = classWith({ id: "bio", title: "Bio 12", color: "#E4557F" });
const LATIN = classWith({ id: "latin", title: "Latin 3", color: "#8E4A7D" });

/** Boot the app with a given set of entries and classes.
 *
 * Waits on the entry form rather than the number, so a run with no entries --
 * where the empty state stands in for the numeral (DECISIONS.md 11.3) -- boots
 * the same way as any other. */
async function boot(entries: unknown[], classes: unknown[]) {
  const fetchMock = stubFetch({
    entries: { body: entries },
    classes: { body: classes },
    stats: { body: statsWith({ entry_count: entries.length }) },
    post: { status: 201, body: ENTRY },
  });
  render(<App />);
  await screen.findByLabelText("Start page");
  return fetchMock;
}

/** The reading log, scoped away from the class manager's own list. */
function log() {
  return within(screen.getByRole("list", { name: "Reading log" }));
}

function bodyOf(fetchMock: ReturnType<typeof stubFetch>, method: string, path: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes(path) &&
      ((init as RequestInit | undefined)?.method ?? "GET") === method,
  );
  expect(call, `no ${method} to ${path}`).toBeTruthy();
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

// --------------------------------------------------------------------------- //
// The default: zero taps in the common case (DECISIONS.md 12.4)
// --------------------------------------------------------------------------- //

describe("the picker's default", () => {
  it("pre-selects the class of the newest entry", async () => {
    await boot([entryWith({ class_id: "bio" }), entryWith({ id: "old", class_id: "latin" })],
      [BIO, LATIN]);

    expect(screen.getByRole("radio", { name: /Bio 12/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: "No class" })).not.toBeChecked();
  });

  it("defaults to No class when the newest entry has none", async () => {
    // Even though an older entry does have one: the picker mirrors what she did
    // last time, so a deliberate "no class" sticks.
    await boot([entryWith({ class_id: null }), entryWith({ id: "old", class_id: "bio" })],
      [BIO]);

    expect(screen.getByRole("radio", { name: "No class" })).toBeChecked();
  });

  it("offers nothing at all when every class is archived", async () => {
    // Archived classes vanish from the picker; with none left there is nothing
    // to pick, so the picker itself is absent rather than showing a lone
    // "No class" that means nothing (DECISIONS.md 12.4).
    await boot([entryWith({ class_id: "bio" })], [classWith({ ...BIO, archived: true })]);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("falls back to No class when the newest entry's class is archived", async () => {
    await boot(
      [entryWith({ class_id: "bio" })],
      [classWith({ ...BIO, archived: true }), LATIN],
    );
    expect(screen.getByRole("radio", { name: "No class" })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Latin 3/ })).not.toBeChecked();
  });

  it("falls back to No class when the newest entry's class no longer exists", async () => {
    // A dangling class_id is not an error (DECISIONS.md 1.3).
    await boot([entryWith({ class_id: "ghost" })], [BIO]);
    expect(screen.getByRole("radio", { name: "No class" })).toBeChecked();
  });

  it("is a pure function of the newest entry and the class list", () => {
    expect(defaultClassId([entryWith({ class_id: "bio" })], [BIO])).toBe("bio");
    expect(defaultClassId([entryWith({ class_id: null })], [BIO])).toBeNull();
    expect(defaultClassId([], [BIO])).toBeNull();
    expect(defaultClassId([entryWith({ class_id: "ghost" })], [BIO])).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// Saving: the picker is never allowed to block one
// --------------------------------------------------------------------------- //

describe("saving", () => {
  async function fillAndSave(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("Start page"), "1");
    await user.type(screen.getByLabelText("End page"), "10");
    await user.click(screen.getByRole("button", { name: "Save" }));
  }

  it("succeeds with no class selected", async () => {
    const fetchMock = await boot([], [BIO]);
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "No class" }));
    await fillAndSave(user);

    await waitFor(() => expect(bodyOf(fetchMock, "POST", "/api/entries")).toBeTruthy());
    const body = bodyOf(fetchMock, "POST", "/api/entries");
    expect(body.class_id).toBeNull();
    expect(body.page_start).toBe(1);
  });

  it("saves with no classes defined at all -- the picker isn't even rendered", async () => {
    const fetchMock = await boot([], []);
    const user = userEvent.setup();

    expect(screen.queryByRole("radio", { name: "No class" })).not.toBeInTheDocument();
    await fillAndSave(user);

    await waitFor(() => expect(bodyOf(fetchMock, "POST", "/api/entries")).toBeTruthy());
    expect(bodyOf(fetchMock, "POST", "/api/entries").class_id).toBeNull();
  });

  it("sends the selected class", async () => {
    const fetchMock = await boot([], [BIO, LATIN]);
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: /Latin 3/ }));
    await fillAndSave(user);

    await waitFor(() => expect(bodyOf(fetchMock, "POST", "/api/entries")).toBeTruthy());
    expect(bodyOf(fetchMock, "POST", "/api/entries").class_id).toBe("latin");
  });

  it("never marks the picker required", async () => {
    await boot([], [BIO]);
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeRequired();
    }
  });
});

// --------------------------------------------------------------------------- //
// The entry list
// --------------------------------------------------------------------------- //

describe("the entry list", () => {
  it("shows the class name beside the dot, so color is not the only signal", async () => {
    await boot([entryWith({ class_id: "bio" })], [BIO]);
    expect(log().getByText("Bio 12")).toBeInTheDocument();
  });

  it("shows an archived class on an entry that already carries it", async () => {
    await boot([entryWith({ class_id: "bio" })], [classWith({ ...BIO, archived: true })]);
    expect(log().getByText("Bio 12")).toBeInTheDocument();
  });

  it("hides archived classes from the picker", async () => {
    await boot([], [classWith({ ...BIO, archived: true }), LATIN]);
    expect(screen.queryByRole("radio", { name: /Bio 12/ })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Latin 3/ })).toBeInTheDocument();
  });

  it("renders nothing for an entry whose class no longer exists", async () => {
    await boot([entryWith({ class_id: "ghost", note: null })], [BIO]);
    expect(log().queryByText("Bio 12")).not.toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------- //
// The manager (DECISIONS.md 12.3, 12.5)
// --------------------------------------------------------------------------- //

describe("the class manager", () => {
  async function openManager(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByText("Classes"));
  }

  it("says plainly that deleting a class keeps the entries", async () => {
    await boot([entryWith({ class_id: "bio" })], [BIO]);
    const user = userEvent.setup();
    await openManager(user);

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(
      screen.getByText(/Everything you logged under it is kept/i),
    ).toBeInTheDocument();
  });

  it("does not delete until the confirmation is accepted", async () => {
    const fetchMock = await boot([], [BIO]);
    const user = userEvent.setup();
    await openManager(user);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Keep it" }));

    const deletes = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
    );
    expect(deletes).toHaveLength(0);
  });

  it("deletes the class and nothing else", async () => {
    const fetchMock = await boot([], [BIO]);
    const user = userEvent.setup();
    await openManager(user);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete the class" }));

    await waitFor(() => {
      const deletes = fetchMock.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deletes).toHaveLength(1);
      expect(String(deletes[0][0])).toBe("/api/classes/bio");
    });
  });

  it("shows no count, total, or comparison anywhere", async () => {
    // DECISIONS.md 12.5: there is nothing to render, because the API returns nothing.
    await boot([entryWith({ class_id: "bio" })], [BIO, LATIN]);
    const user = userEvent.setup();
    await openManager(user);

    const manager = screen.getByText("Classes").closest("details");
    const text = manager?.textContent ?? "";
    expect(text).not.toMatch(/\d+\s*(pages?|entries|entry)\b/i);
    expect(text).not.toMatch(/ahead|behind|most|least|compared/i);
  });

  it("creates a class with the first unused palette color", async () => {
    const palette = installPalette();
    const fetchMock = await boot([], [classWith({ ...BIO, color: palette[0] })]);
    const user = userEvent.setup();
    await openManager(user);

    await user.type(screen.getByLabelText("New class"), "Latin 3");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(bodyOf(fetchMock, "POST", "/api/classes")).toBeTruthy());
    const body = bodyOf(fetchMock, "POST", "/api/classes");
    expect(body.title).toBe("Latin 3");
    expect(body.color).toBe(palette[1]);
  });

  it("archives without deleting", async () => {
    const fetchMock = await boot([], [BIO]);
    const user = userEvent.setup();
    await openManager(user);

    await user.click(screen.getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(bodyOf(fetchMock, "PATCH", "/api/classes/bio")).toBeTruthy());
    expect(bodyOf(fetchMock, "PATCH", "/api/classes/bio")).toEqual({ archived: true });
  });
});

// --------------------------------------------------------------------------- //
// Palette selection, without naming a single color (DECISIONS.md 12.2)
// --------------------------------------------------------------------------- //

describe("suggestColor", () => {
  it("returns null when the palette has not resolved, so no color is sent", () => {
    expect(suggestColor([], 0)).toBeNull();
  });

  it("picks the first color not already in use", () => {
    const palette = installPalette();
    expect(suggestColor([], 0)).toBe(palette[0]);
    expect(suggestColor([palette[0]], 1)).toBe(palette[1]);
    expect(suggestColor([palette[1]], 1)).toBe(palette[0]);
  });

  it("ignores case when deciding what is in use", () => {
    const palette = installPalette();
    expect(suggestColor([palette[0].toUpperCase()], 1)).toBe(palette[1]);
  });

  it("wraps by count once every color is taken", () => {
    const palette = installPalette();
    expect(suggestColor(palette, palette.length)).toBe(palette[0]);
    expect(suggestColor(palette, palette.length + 1)).toBe(palette[1]);
  });
});
