import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi } from "../test/mockApi";
import { RollForm } from "./RollForm";

const ref = (id: string, name: string, extra: object = {}) => ({
  id,
  name,
  archived_at: null,
  ...extra,
});

let api: MockApi;

beforeEach(() => {
  localStorage.clear();
  api = installMockApi({
    refs: {
      cameras: [ref("cam1", "Nikon FM2"), ref("cam2", "Olympus XA"), ref("cam3", "Leica M3")],
      lenses: [ref("len1", "50mm f/1.8"), ref("len2", "35mm f/2")],
      formats: [ref("f35", "35mm"), ref("f120", "120")],
      films: [
        ref("film1", "Tri-X", { type: "bw", box_iso: 400 }),
        ref("film2", "Portra 160", { type: "colour", box_iso: 160 }),
      ],
      developers: [ref("dev1", "HC-110"), ref("dev2", "Rodinal")],
      filters: [ref("fil1", "Yellow")],
    },
    lastRolls: {
      cam1: {
        id: "old",
        lens: { id: "len2", name: "35mm f/2" },
        format: { id: "f120", name: "120" },
      },
      cam2: { id: "old2", lens: null, format: { id: "f35", name: "35mm" } },
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={client}>
      <RollForm />
    </QueryClientProvider>,
  );
  return user;
}

/** Wait for the reference lists to load, then pick options by label. */
async function choose(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  const select = screen.getByLabelText(label);
  await waitFor(() => expect(screen.getByRole("option", { name: option })).toBeInTheDocument());
  await user.selectOptions(select, option);
}

it("picking a camera fills lens and format from its last roll", async () => {
  const user = renderForm();
  await choose(user, "Camera", "Nikon FM2");

  await waitFor(() => expect(screen.getByLabelText("Lens")).toHaveValue("len2"));
  expect(screen.getByLabelText("Format")).toHaveValue("f120");
});

it("a fixed-lens camera's last roll sets the lens to N/A", async () => {
  const user = renderForm();
  await choose(user, "Camera", "Nikon FM2");
  await waitFor(() => expect(screen.getByLabelText("Lens")).toHaveValue("len2"));

  await choose(user, "Camera", "Olympus XA");
  await waitFor(() => expect(screen.getByLabelText("Lens")).toHaveValue(""));
  expect(screen.getByLabelText("Format")).toHaveValue("f35");
});

it("a camera with no rolls leaves lens and format alone", async () => {
  const user = renderForm();
  await choose(user, "Format", "35mm");
  await choose(user, "Camera", "Leica M3");
  await waitFor(() => expect(api.calls.some((c) => c.url.endsWith("cam3/last-roll"))).toBe(true));
  expect(screen.getByLabelText("Format")).toHaveValue("f35");
});

it("picking a film sets EI to box ISO and updates stops live", async () => {
  const user = renderForm();
  await choose(user, "Film", "Tri-X");
  expect(screen.getByLabelText("EI")).toHaveValue("400");
  expect(screen.getByText(/Stops vs box/)).toHaveTextContent("0");

  await user.clear(screen.getByLabelText("EI"));
  await user.type(screen.getByLabelText("EI"), "800");
  expect(screen.getByText(/Stops vs box/)).toHaveTextContent("+1");

  await user.clear(screen.getByLabelText("EI"));
  await user.type(screen.getByLabelText("EI"), "250");
  expect(screen.getByText(/Stops vs box/)).toHaveTextContent("-0.7");

  await choose(user, "Film", "Portra 160");
  expect(screen.getByLabelText("EI")).toHaveValue("160");
  expect(screen.getByText(/Stops vs box/)).toHaveTextContent("box ISO 160");
});

it("EI input accepts 12.5", async () => {
  const user = renderForm();
  await choose(user, "Film", "Tri-X");
  await user.clear(screen.getByLabelText("EI"));
  await user.type(screen.getByLabelText("EI"), "12.5");
  expect(screen.getByLabelText("EI")).toHaveValue("12.5");
  expect(screen.getByText(/Stops vs box/)).toHaveTextContent("-5");
});

it("rejects an EI that is not a number, without calling the API", async () => {
  const user = renderForm();
  await choose(user, "Camera", "Leica M3");
  await choose(user, "Format", "35mm");
  await choose(user, "Developer", "HC-110");
  await choose(user, "Film", "Tri-X");
  await user.clear(screen.getByLabelText("EI"));
  await user.type(screen.getByLabelText("EI"), "fast");
  await user.click(screen.getByRole("button", { name: "Log roll" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("EI must be a positive number");
  expect(api.calls.some((c) => c.method === "POST")).toBe(false);
});

it("stock toggle is below the fold and defaults on", async () => {
  renderForm();
  const toggle = screen.getByLabelText("Counts against stock");
  expect(toggle).toBeChecked();
  // it comes after the fields people fill in, so it is below the fold on a phone
  for (const label of ["Camera", "Film", "EI", "Subject", "Notes"]) {
    const field = screen.getByLabelText(label);
    expect(field.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
});

it("after save keeps setup fields and clears subject, notes and dev time", async () => {
  const user = renderForm();
  await choose(user, "Camera", "Nikon FM2");
  await waitFor(() => expect(screen.getByLabelText("Lens")).toHaveValue("len2"));
  await choose(user, "Film", "Tri-X");
  await choose(user, "Developer", "HC-110");
  await user.type(screen.getByLabelText("Development time (min)"), "9.5");
  await user.type(screen.getByLabelText("Subject"), "Harbour");
  await user.type(screen.getByLabelText("Notes"), "Pushed");
  await user.click(screen.getByRole("button", { name: "Log roll" }));

  await screen.findByText("Roll logged.");
  const post = api.calls.find((c) => c.method === "POST")!;
  expect(post.body).toMatchObject({
    camera_id: "cam1",
    lens_id: "len2",
    format_id: "f120",
    film_id: "film1",
    ei: 400,
    developer_id: "dev1",
    dev_time_min: 9.5,
    subject: "Harbour",
    notes: "Pushed",
    counts_against_stock: true,
  });

  // setup kept
  expect(screen.getByLabelText("Camera")).toHaveValue("cam1");
  expect(screen.getByLabelText("Lens")).toHaveValue("len2");
  expect(screen.getByLabelText("Format")).toHaveValue("f120");
  expect(screen.getByLabelText("Developer")).toHaveValue("dev1");
  // roll-specific fields cleared
  expect(screen.getByLabelText("Subject")).toHaveValue("");
  expect(screen.getByLabelText("Notes")).toHaveValue("");
  expect(screen.getByLabelText("Development time (min)")).toHaveValue("");
  expect(screen.getByLabelText("Film")).toHaveValue("");
  expect(screen.getByLabelText("EI")).toHaveValue("");

  // and remembered for next time
  expect(JSON.parse(localStorage.getItem("darkroom.setup")!)).toEqual({
    camera_id: "cam1",
    lens_id: "len2",
    format_id: "f120",
    developer_id: "dev1",
  });
});

it("starts from the remembered setup", async () => {
  localStorage.setItem(
    "darkroom.setup",
    JSON.stringify({ camera_id: "cam2", lens_id: "", format_id: "f35", developer_id: "dev2" }),
  );
  renderForm();
  await waitFor(() => expect(screen.getByLabelText("Camera")).toHaveValue("cam2"));
  expect(screen.getByLabelText("Format")).toHaveValue("f35");
  expect(screen.getByLabelText("Developer")).toHaveValue("dev2");
});
