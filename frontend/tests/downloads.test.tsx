import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Downloads } from "../components/Downloads";
import type { GenerateResponse } from "../types/api";

const RESULT: GenerateResponse = {
  status: "completed",
  request_id: "req1",
  specification: {
    document_type: "3d_part",
    units: "mm",
    name: "shaft",
    operation: { type: "cylinder", radius: 15, height: 120, through: false },
  },
  units: "mm",
  generation_time_ms: 800,
  files: {
    step: {
      format: "step",
      filename: "shaft.step",
      bytes: 5675,
      download_url: "/download/TOK?format=step",
    },
    stl: {
      format: "stl",
      filename: "shaft.stl",
      bytes: 25084,
      download_url: "/download/TOK?format=stl",
    },
  },
};

describe("Downloads", () => {
  it("renders STEP and STL links resolved against the API base", () => {
    render(<Downloads result={RESULT} />);
    const step = screen.getByRole("link", { name: /download step/i });
    const stl = screen.getByRole("link", { name: /download stl/i });
    expect(step).toHaveAttribute("href", expect.stringContaining("/download/TOK"));
    expect(step).toHaveAttribute("download", "shaft.step");
    expect(stl).toHaveAttribute("download", "shaft.stl");
    expect(screen.getByText("shaft.step")).toBeInTheDocument();
  });

  it("renders a Re-mint button that calls the handler", () => {
    const onRemint = vi.fn();
    render(<Downloads result={RESULT} onRemint={onRemint} />);
    fireEvent.click(screen.getByRole("button", { name: /re-mint/i }));
    expect(onRemint).toHaveBeenCalledOnce();
  });

  it("disables the Re-mint button while re-minting", () => {
    render(<Downloads result={RESULT} onRemint={() => {}} remintBusy />);
    const button = screen.getByText("Re-minting…");
    expect(button).toBeDisabled();
  });
});
