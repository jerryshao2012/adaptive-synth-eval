"use client";

import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  EvalRunParameters,
  MonitoringAction,
  SamplingStrategy,
} from "@/types/evaluation";

interface EvaluationConfigDialogProps {
  open: boolean;
  action: MonitoringAction;
  initialValues: EvalRunParameters;
  onOpenChange: (open: boolean) => void;
  onSubmit: (parameters: EvalRunParameters) => Promise<void>;
  serverError?: string | null;
}

interface ActionContent {
  title: string;
  description: string;
  pendingLabel: string;
}

const ACTION_CONTENT: Record<MonitoringAction, ActionContent> = {
  start: {
    title: "Start evaluation",
    description: "Start begins monitoring from the first source row.",
    pendingLabel: "Starting evaluation",
  },
  continue: {
    title: "Continue evaluation",
    description:
      "Continue resumes from the saved cursor and applies these settings to the remaining windows.",
    pendingLabel: "Continuing evaluation",
  },
  reevaluate: {
    title: "Re-evaluate run",
    description:
      "Re-evaluate rescans from the first source row and reuses fingerprint-matching results.",
    pendingLabel: "Re-evaluating run",
  },
};

const CONTROL_CLASS_NAME =
  "h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20";
const LABEL_CLASS_NAME = "mb-1.5 block text-xs font-medium text-foreground";
const HELPER_CLASS_NAME = "mt-1.5 text-xs text-muted-foreground";
const ERROR_CLASS_NAME = "mt-1.5 text-xs text-destructive";

function toOptionalNumber(value: number | null): string {
  return value === null ? "" : String(value);
}

function parsePositiveInteger(value: string): number | null {
  const parsed = Number(value);
  return value.trim() !== "" && Number.isInteger(parsed) && parsed > 0
    ? parsed
    : null;
}

function EvaluationConfigDialogSession({
  open,
  action,
  initialValues,
  onOpenChange,
  onSubmit,
  serverError,
}: EvaluationConfigDialogProps) {
  const [samplingStrategy, setSamplingStrategy] =
    useState<SamplingStrategy>(initialValues.samplingStrategy);
  const [sampleSizeText, setSampleSizeText] = useState(
    String(initialValues.sampleSize)
  );
  const [intervalMinutesText, setIntervalMinutesText] = useState(
    String(initialValues.intervalMinutes)
  );
  const [maxWindowsText, setMaxWindowsText] = useState(
    toOptionalNumber(initialValues.maxWindows)
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const content = ACTION_CONTENT[action];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const sampleSize = parsePositiveInteger(sampleSizeText);
    const intervalMinutes = parsePositiveInteger(intervalMinutesText);
    const maxWindows =
      maxWindowsText.trim() === ""
        ? null
        : parsePositiveInteger(maxWindowsText);
    const nextErrors: Record<string, string> = {};

    if (sampleSize === null) {
      nextErrors.sampleSize = "Sample size must be a positive integer.";
    }
    if (intervalMinutes === null) {
      nextErrors.intervalMinutes =
        "Interval minutes must be a positive integer.";
    }
    if (maxWindowsText.trim() !== "" && maxWindows === null) {
      nextErrors.maxWindows =
        "Max windows must be a positive integer or left blank.";
    }

    setErrors(nextErrors);
    setSubmissionError(null);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      await onSubmit({
        samplingStrategy,
        sampleSize: sampleSize as number,
        intervalMinutes: intervalMinutes as number,
        maxWindows,
      });
      onOpenChange(false);
    } catch (error) {
      setSubmissionError(
        error instanceof Error
          ? error.message
          : "The evaluation could not be launched."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!isSubmitting) onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="max-w-md border-border bg-card text-foreground"
        showCloseButton={!isSubmitting}
      >
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            {content.title}
          </DialogTitle>
          <DialogDescription>{content.description}</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" noValidate onSubmit={handleSubmit}>
          <div>
            <label className={LABEL_CLASS_NAME} htmlFor="evaluation-sampling-strategy">
              Sampling strategy
            </label>
            <select
              id="evaluation-sampling-strategy"
              className={CONTROL_CLASS_NAME}
              value={samplingStrategy}
              onChange={(event) =>
                setSamplingStrategy(event.target.value as SamplingStrategy)
              }
              disabled={isSubmitting}
            >
              <option value="all">All rows</option>
              <option value="random">Random sample</option>
              <option value="systematic">Systematic sample</option>
            </select>
            <p className={HELPER_CLASS_NAME}>
              Choose how rows are selected from each evaluation window.
            </p>
          </div>

          <div>
            <label className={LABEL_CLASS_NAME} htmlFor="evaluation-sample-size">
              Sample size
            </label>
            <input
              id="evaluation-sample-size"
              className={CONTROL_CLASS_NAME}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={sampleSizeText}
              onChange={(event) => setSampleSizeText(event.target.value)}
              disabled={isSubmitting || samplingStrategy === "all"}
              aria-invalid={Boolean(errors.sampleSize)}
              aria-describedby={
                errors.sampleSize
                  ? "evaluation-sample-size-error"
                  : "evaluation-sample-size-help"
              }
            />
            {errors.sampleSize ? (
              <p
                className={ERROR_CLASS_NAME}
                id="evaluation-sample-size-error"
              >
                {errors.sampleSize}
              </p>
            ) : (
              <p className={HELPER_CLASS_NAME} id="evaluation-sample-size-help">
                {samplingStrategy === "all"
                  ? "All rows are evaluated, so sample size is not used."
                  : "Rows selected from each evaluation window."}
              </p>
            )}
          </div>

          <div>
            <label
              className={LABEL_CLASS_NAME}
              htmlFor="evaluation-interval-minutes"
            >
              Interval minutes
            </label>
            <input
              id="evaluation-interval-minutes"
              className={CONTROL_CLASS_NAME}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={intervalMinutesText}
              onChange={(event) => setIntervalMinutesText(event.target.value)}
              disabled={isSubmitting}
              aria-invalid={Boolean(errors.intervalMinutes)}
              aria-describedby={
                errors.intervalMinutes
                  ? "evaluation-interval-minutes-error"
                  : "evaluation-interval-minutes-help"
              }
            />
            {errors.intervalMinutes ? (
              <p
                className={ERROR_CLASS_NAME}
                id="evaluation-interval-minutes-error"
              >
                {errors.intervalMinutes}
              </p>
            ) : (
              <p
                className={HELPER_CLASS_NAME}
                id="evaluation-interval-minutes-help"
              >
                Source rows grouped into each evaluation window.
              </p>
            )}
          </div>

          <div>
            <label className={LABEL_CLASS_NAME} htmlFor="evaluation-max-windows">
              Max windows
            </label>
            <input
              id="evaluation-max-windows"
              className={CONTROL_CLASS_NAME}
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={maxWindowsText}
              onChange={(event) => setMaxWindowsText(event.target.value)}
              disabled={isSubmitting}
              aria-invalid={Boolean(errors.maxWindows)}
              aria-describedby={
                errors.maxWindows
                  ? "evaluation-max-windows-error"
                  : "evaluation-max-windows-help"
              }
            />
            {errors.maxWindows ? (
              <p className={ERROR_CLASS_NAME} id="evaluation-max-windows-error">
                {errors.maxWindows}
              </p>
            ) : (
              <p className={HELPER_CLASS_NAME} id="evaluation-max-windows-help">
                Leave blank to evaluate all available windows.
              </p>
            )}
          </div>

          {(serverError || submissionError) && (
            <p
              className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              role="alert"
            >
              {submissionError || serverError}
            </p>
          )}

          <DialogFooter className="mt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? content.pendingLabel : content.title}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EvaluationConfigDialog(props: EvaluationConfigDialogProps) {
  const resetKey = props.open
    ? [
        props.action,
        props.initialValues.samplingStrategy,
        props.initialValues.sampleSize,
        props.initialValues.intervalMinutes,
        props.initialValues.maxWindows ?? "unlimited",
      ].join(":")
    : "closed";

  return <EvaluationConfigDialogSession key={resetKey} {...props} />;
}

export type { EvaluationConfigDialogProps };
