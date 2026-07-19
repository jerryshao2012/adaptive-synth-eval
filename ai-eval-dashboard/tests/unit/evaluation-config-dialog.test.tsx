// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvaluationConfigDialog } from "@/components/dashboard/evaluation-config-dialog";
import type { EvalRunParameters, MonitoringAction } from "@/types/evaluation";

const INITIAL_VALUES: EvalRunParameters = {
  samplingStrategy: "systematic",
  sampleSize: 24,
  intervalMinutes: 15,
  maxWindows: 6,
};

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof EvaluationConfigDialog>> = {}
) {
  const props: React.ComponentProps<typeof EvaluationConfigDialog> = {
    open: true,
    action: "start",
    initialValues: INITIAL_VALUES,
    onOpenChange: vi.fn(),
    onSubmit: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };

  return { ...render(<EvaluationConfigDialog {...props} />), props };
}

afterEach(cleanup);

describe("EvaluationConfigDialog", () => {
  it.each<[MonitoringAction, string, RegExp]>([
    ["start", "Start evaluation", /begins monitoring from the first source row/i],
    ["continue", "Continue evaluation", /resumes from the saved cursor/i],
    ["reevaluate", "Re-evaluate run", /rescans from the first source row and reuses fingerprint-matching results/i],
  ])("shows %s action title and guidance", (action, title, guidance) => {
    renderDialog({ action });

    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(screen.getByText(guidance)).toBeTruthy();
  });

  it("prefills all controls from the selected run settings", () => {
    renderDialog();

    expect((screen.getByLabelText("Sampling strategy") as HTMLSelectElement).value).toBe("systematic");
    expect((screen.getByLabelText("Sample size") as HTMLInputElement).value).toBe("24");
    expect((screen.getByLabelText("Interval minutes") as HTMLInputElement).value).toBe("15");
    expect((screen.getByLabelText("Max windows") as HTMLInputElement).value).toBe("6");
  });

  it("resets local edits from new initial values each time it opens", async () => {
    const user = userEvent.setup();
    const { rerender, props } = renderDialog();
    const interval = screen.getByLabelText("Interval minutes");
    await user.clear(interval);
    await user.type(interval, "99");

    rerender(<EvaluationConfigDialog {...props} open={false} />);
    rerender(
      <EvaluationConfigDialog
        {...props}
        open
        action="continue"
        initialValues={{ ...INITIAL_VALUES, intervalMinutes: 30, maxWindows: null }}
      />
    );

    expect((screen.getByLabelText("Interval minutes") as HTMLInputElement).value).toBe("30");
    expect((screen.getByLabelText("Max windows") as HTMLInputElement).value).toBe("");
  });

  it("disables sample size for all rows and enables it for sampled strategies", async () => {
    const user = userEvent.setup();
    renderDialog();
    const strategy = screen.getByLabelText("Sampling strategy");
    const sampleSize = screen.getByLabelText("Sample size");

    await user.selectOptions(strategy, "all");
    expect((sampleSize as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/all rows are evaluated, so sample size is not used/i)).toBeTruthy();

    await user.selectOptions(strategy, "random");
    expect((sampleSize as HTMLInputElement).disabled).toBe(false);
  });

  it.each([
    ["Sample size", "random", "Sample size must be a positive integer."],
    ["Interval minutes", "systematic", "Interval minutes must be a positive integer."],
    ["Max windows", "systematic", "Max windows must be a positive integer or left blank."],
  ])("validates %s before submission", async (label, strategy, message) => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderDialog({ onSubmit });
    await user.selectOptions(screen.getByLabelText("Sampling strategy"), strategy);
    const control = screen.getByLabelText(label);
    fireEvent.change(control, { target: { value: "0" } });

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));

    expect(screen.getByText(message)).toBeTruthy();
    expect(control.getAttribute("aria-invalid")).toBe("true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits blank max windows as unlimited", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderDialog({ onSubmit });
    await user.clear(screen.getByLabelText("Max windows"));

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        samplingStrategy: "systematic",
        sampleSize: 24,
        intervalMinutes: 15,
        maxWindows: null,
      })
    );
  });

  it("shows a server error without closing", () => {
    const onOpenChange = vi.fn();
    renderDialog({ serverError: "The evaluation launch is already active.", onOpenChange });

    expect(screen.getByRole("alert").textContent).toContain("The evaluation launch is already active.");
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("closes without submitting when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderDialog({ onOpenChange, onSubmit });

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("stays open and pending until async submission resolves", async () => {
    const user = userEvent.setup();
    let resolveSubmit: (() => void) | undefined;
    const onSubmit = vi.fn(
      () => new Promise<void>((resolve) => { resolveSubmit = resolve; })
    );
    const onOpenChange = vi.fn();
    renderDialog({ onSubmit, onOpenChange });

    await user.click(screen.getByRole("button", { name: "Start evaluation" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Starting evaluation" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);

    resolveSubmit?.();
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });
});
