"use client";

import { FormEvent, useRef, useState } from "react";

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

function parseNonNegativeInteger(value: string): number | null {
  const parsed = Number(value);
  return value.trim() !== "" && Number.isInteger(parsed) && parsed >= 0
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
  const [triggeredLookbackText, setTriggeredLookbackText] = useState(
    String(initialValues.triggeredLookback ?? 2)
  );
  const [triggeredLookaheadText, setTriggeredLookaheadText] = useState(
    String(initialValues.triggeredLookahead ?? 2)
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fallbackSampleSize] = useState(initialValues.sampleSize);
  const sampleSizeRef = useRef<HTMLInputElement>(null);
  const intervalMinutesRef = useRef<HTMLInputElement>(null);
  const maxWindowsRef = useRef<HTMLInputElement>(null);
  const triggeredLookbackRef = useRef<HTMLInputElement>(null);
  const triggeredLookaheadRef = useRef<HTMLInputElement>(null);

  const content = ACTION_CONTENT[action];

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const parsedSampleSize = parsePositiveInteger(sampleSizeText);
    const sampleSize =
      samplingStrategy === "all"
        ? parsedSampleSize ?? fallbackSampleSize
        : parsedSampleSize;
    const intervalMinutes = parsePositiveInteger(intervalMinutesText);
    const maxWindows =
      maxWindowsText.trim() === ""
        ? null
        : parsePositiveInteger(maxWindowsText);
    const triggeredLookback = parseNonNegativeInteger(triggeredLookbackText);
    const triggeredLookahead = parseNonNegativeInteger(triggeredLookaheadText);
    const nextErrors: Record<string, string> = {};

    if (samplingStrategy !== "all" && sampleSize === null) {
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
    if (samplingStrategy === "triggered") {
      if (triggeredLookback === null) {
        nextErrors.triggeredLookback =
          "Lookback must be a non-negative integer.";
      }
      if (triggeredLookahead === null) {
        nextErrors.triggeredLookahead =
          "Lookahead must be a non-negative integer.";
      }
    }

    setErrors(nextErrors);
    setSubmissionError(null);
    if (Object.keys(nextErrors).length > 0) {
      if (nextErrors.sampleSize) {
        sampleSizeRef.current?.focus();
      } else if (nextErrors.intervalMinutes) {
        intervalMinutesRef.current?.focus();
      } else if (nextErrors.maxWindows) {
        maxWindowsRef.current?.focus();
      } else if (nextErrors.triggeredLookback) {
        triggeredLookbackRef.current?.focus();
      } else if (nextErrors.triggeredLookahead) {
        triggeredLookaheadRef.current?.focus();
      }
      return;
    }

    setIsSubmitting(true);
    try {
      const parameters: EvalRunParameters = {
        samplingStrategy,
        sampleSize: sampleSize as number,
        intervalMinutes: intervalMinutes as number,
        maxWindows,
      };
      if (samplingStrategy === "triggered") {
        parameters.triggeredLookback = triggeredLookback as number;
        parameters.triggeredLookahead = triggeredLookahead as number;
      }
      await onSubmit(parameters);
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
        className="max-h-[calc(100dvh-2rem)] max-w-md overflow-y-auto border-border bg-card text-foreground"
        showCloseButton={!isSubmitting}
      >
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            {content.title}
          </DialogTitle>
          <DialogDescription>{content.description}</DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          noValidate
          onSubmit={handleSubmit}
          aria-busy={isSubmitting}
        >
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
              <option value="triggered">Triggered (retroactive)</option>
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
              ref={sampleSizeRef}
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
                role="alert"
                aria-live="polite"
              >
                {errors.sampleSize}
              </p>
            ) : (
              <p className={HELPER_CLASS_NAME} id="evaluation-sample-size-help">
                {samplingStrategy === "all"
                  ? "All rows are evaluated, so sample size is not used."
                  : samplingStrategy === "triggered"
                    ? "Hard capture budget per window: triggers first, then nearest context."
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
              ref={intervalMinutesRef}
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
                role="alert"
                aria-live="polite"
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
              ref={maxWindowsRef}
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
              <p
                className={ERROR_CLASS_NAME}
                id="evaluation-max-windows-error"
                role="alert"
                aria-live="polite"
              >
                {errors.maxWindows}
              </p>
            ) : (
              <p className={HELPER_CLASS_NAME} id="evaluation-max-windows-help">
                Leave blank to evaluate all available windows.
              </p>
            )}
          </div>

          {samplingStrategy === "triggered" && (
            <>
              <div>
                <label
                  className={LABEL_CLASS_NAME}
                  htmlFor="evaluation-triggered-lookback"
                >
                  Lookback turns
                </label>
                <input
                  id="evaluation-triggered-lookback"
                  ref={triggeredLookbackRef}
                  className={CONTROL_CLASS_NAME}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  value={triggeredLookbackText}
                  onChange={(event) => setTriggeredLookbackText(event.target.value)}
                  disabled={isSubmitting}
                  aria-invalid={Boolean(errors.triggeredLookback)}
                  aria-describedby={
                    errors.triggeredLookback
                      ? "evaluation-triggered-lookback-error"
                      : "evaluation-triggered-lookback-help"
                  }
                />
                {errors.triggeredLookback ? (
                  <p
                    className={ERROR_CLASS_NAME}
                    id="evaluation-triggered-lookback-error"
                    role="alert"
                    aria-live="polite"
                  >
                    {errors.triggeredLookback}
                  </p>
                ) : (
                  <p
                    className={HELPER_CLASS_NAME}
                    id="evaluation-triggered-lookback-help"
                  >
                    Number of prior turns to include when trigger fires.
                  </p>
                )}
              </div>

              <div>
                <label
                  className={LABEL_CLASS_NAME}
                  htmlFor="evaluation-triggered-lookahead"
                >
                  Lookahead turns
                </label>
                <input
                  id="evaluation-triggered-lookahead"
                  ref={triggeredLookaheadRef}
                  className={CONTROL_CLASS_NAME}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  value={triggeredLookaheadText}
                  onChange={(event) => setTriggeredLookaheadText(event.target.value)}
                  disabled={isSubmitting}
                  aria-invalid={Boolean(errors.triggeredLookahead)}
                  aria-describedby={
                    errors.triggeredLookahead
                      ? "evaluation-triggered-lookahead-error"
                      : "evaluation-triggered-lookahead-help"
                  }
                />
                {errors.triggeredLookahead ? (
                  <p
                    className={ERROR_CLASS_NAME}
                    id="evaluation-triggered-lookahead-error"
                    role="alert"
                    aria-live="polite"
                  >
                    {errors.triggeredLookahead}
                  </p>
                ) : (
                  <p
                    className={HELPER_CLASS_NAME}
                    id="evaluation-triggered-lookahead-help"
                  >
                    Number of pending future turns to capture after trigger.
                  </p>
                )}
              </div>

            </>
          )}

          {(serverError || submissionError) && (
            <p
              className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              role="alert"
              aria-live="polite"
            >
              {submissionError || serverError}
            </p>
          )}

          <p className="sr-only" role="status" aria-live="polite">
            {isSubmitting ? "Evaluation launch is in progress." : ""}
          </p>

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
  if (!props.open) {
    return <Dialog open={false} onOpenChange={props.onOpenChange} />;
  }

  return <EvaluationConfigDialogSession key={props.action} {...props} />;
}

export type { EvaluationConfigDialogProps };
