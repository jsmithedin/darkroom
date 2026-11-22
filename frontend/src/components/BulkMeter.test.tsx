import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { BulkMeter } from "./BulkMeter";

it("shows metres and exposures left, with a meter", () => {
  render(<BulkMeter left_mm={7300} length_mm={17000} exposures_left={185} />);
  expect(screen.getByText(/7.3 m left of 17 m/)).toBeInTheDocument();
  expect(screen.getByText(/185 exposures left/)).toBeInTheDocument();
  const meter = screen.getByRole("meter");
  expect(meter).toHaveAttribute("aria-valuenow", "7300");
  expect(meter).toHaveAttribute("aria-valuemax", "17000");
});

it("shows how far an overdrawn spool is short", () => {
  render(<BulkMeter left_mm={-790} length_mm={2000} exposures_left={0} />);
  expect(screen.getByText(/Overdrawn by 0.79 m/)).toBeInTheDocument();
  expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "0");
});
