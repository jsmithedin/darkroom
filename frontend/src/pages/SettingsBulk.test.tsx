import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { SettingsBulk } from "./SettingsBulk";

const spool = {
  id: "b1",
  label: "Bulk 1",
  film: { id: "f1", name: "Fomapan 100", type: "bw" },
  length_mm: 17000,
  cost_pence: null,
  supplier: null,
  bought_on: null,
  used_before_mm: 9700,
  finished: false,
  notes: null,
  cassettes_loaded: 0,
  used_mm: 9700,
  left_mm: 7300,
  exposures_left: 185,
  cost_per_36_pence: null,
};

let api: MockApi;
let deleteRefusal = false;

beforeEach(() => {
  deleteRefusal = false;
  api = installMockApi({
    refs: { films: [{ id: "f1", name: "Fomapan 100", archived_at: null }] },
    handler: (url, method, body) => {
      if (url === "/api/settings" && method === "GET") {
        return reply({ leader_mm: 250, frame_pitch_mm: 38, timezone: "Europe/London" });
      }
      if (url === "/api/settings" && method === "PATCH") return reply(body);
      if (url.startsWith("/api/bulk-rolls") && method === "GET") return reply([spool]);
      if (url === "/api/bulk-rolls" && method === "POST") return reply({ ...spool, ...body }, 201);
      if (url === "/api/bulk-rolls/b1" && method === "DELETE") {
        return deleteRefusal
          ? reply({ detail: "'Bulk 1' has 2 cassette load(s) recorded against it." }, 409)
          : reply(null, 204);
      }
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("shows the current maths and saves changes", async () => {
  const { user } = renderApp(<SettingsBulk />);
  const leader = await screen.findByLabelText("Leader per cassette (mm)");
  await waitFor(() => expect(leader).toHaveValue("250"));
  expect(screen.getByLabelText("Frame pitch (mm per exposure)")).toHaveValue("38");

  await user.clear(leader);
  await user.type(leader, "300");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  const patch = api.calls.find((c) => c.method === "PATCH" && c.url === "/api/settings")!;
  expect(patch.body).toEqual({ leader_mm: 300, frame_pitch_mm: 38, timezone: "Europe/London" });
});

it("will not save a non-positive leader", async () => {
  const { user } = renderApp(<SettingsBulk />);
  const leader = await screen.findByLabelText("Leader per cassette (mm)");
  await waitFor(() => expect(leader).toHaveValue("250"));
  await user.clear(leader);
  await user.type(leader, "0");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

it("lists spools with their meter and unpriced status", async () => {
  renderApp(<SettingsBulk />);
  const list = await screen.findByRole("region", { name: "Bulk spools" });
  expect(await within(list).findByText("Bulk 1")).toBeInTheDocument();
  expect(within(list).getByText(/unpriced/)).toBeInTheDocument();
  expect(within(list).getByText(/185 exposures left/)).toBeInTheDocument();
});

it("adds a spool, converting metres and pounds exactly, with optional fields empty", async () => {
  const { user } = renderApp(<SettingsBulk />);
  await user.click(await screen.findByRole("button", { name: "Add spool" }));
  const form = screen.getByRole("form", { name: "Add spool" });
  await waitFor(() => expect(within(form).getByRole("option", { name: "Fomapan 100" })).toBeInTheDocument());
  await user.type(within(form).getByLabelText("Label"), "Bulk 2");
  await user.selectOptions(within(form).getByLabelText("Film"), "Fomapan 100");
  await user.type(within(form).getByLabelText("Length (m)"), "30.48");
  await user.type(within(form).getByLabelText("Price (£, optional)"), "30");
  await user.click(within(form).getByRole("button", { name: "Add spool" }));

  await waitFor(() => expect(screen.queryByRole("form", { name: "Add spool" })).not.toBeInTheDocument());
  const post = api.calls.find((c) => c.method === "POST" && c.url === "/api/bulk-rolls")!;
  expect(post.body).toEqual({
    label: "Bulk 2",
    film_id: "f1",
    length_mm: 30480,
    cost_pence: 3000,
    supplier: null,
    bought_on: null,
    used_before_mm: 0,
    finished: false,
    notes: null,
  });
});

it("an unpriced spool needs no price", async () => {
  const { user } = renderApp(<SettingsBulk />);
  await user.click(await screen.findByRole("button", { name: "Add spool" }));
  const form = screen.getByRole("form", { name: "Add spool" });
  await waitFor(() => expect(within(form).getByRole("option", { name: "Fomapan 100" })).toBeInTheDocument());
  await user.type(within(form).getByLabelText("Label"), "Bulk 3");
  await user.selectOptions(within(form).getByLabelText("Film"), "Fomapan 100");
  await user.type(within(form).getByLabelText("Length (m)"), "17");
  expect(within(form).getByRole("button", { name: "Add spool" })).toBeEnabled();
  await user.type(within(form).getByLabelText("Price (£, optional)"), "abc");
  expect(within(form).getByRole("button", { name: "Add spool" })).toBeDisabled();
});

it("deleting a spool with loads shows the server's refusal", async () => {
  deleteRefusal = true;
  const { user } = renderApp(<SettingsBulk />);
  await screen.findByText("Bulk 1");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cassette load(s) recorded");
});
