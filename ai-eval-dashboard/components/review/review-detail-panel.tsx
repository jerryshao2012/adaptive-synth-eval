"use client";

import { useEffect, useReducer, useRef, useCallback, useMemo } from "react";
import { randomUUID } from "@/lib/utils-client";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { MetricBadge } from "@/components/shared/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { METRIC_THRESHOLDS } from "@/lib/metrics";
import { MetricScoreRow } from "@/components/review/metric-score-row";
import {
  X,
  User,
  MessageSquare,
  FileText,
  Loader2,
} from "lucide-react";
import { format, parseISO } from "date-fns";
import type {
  EvaluationRecord,
  HumanReview,
  MetricScoreStatus,
} from "@/types/evaluation";

// ---- Reducer ----

type ReviewFormAction =
  | {
      type: "SET_SAFETY_SCORE";
      metricKey: string;
      score: number;
    }
  | {
      type: "SET_PERFORMANCE_SCORE";
      metricKey: string;
      score: number;
    }
  | {
      type: "SET_SAFETY_STATUS";
      metricKey: string;
      status: MetricScoreStatus;
    }
  | {
      type: "SET_PERFORMANCE_STATUS";
      metricKey: string;
      status: MetricScoreStatus;
    }
  | { type: "SET_OVERALL_STATUS"; status: MetricScoreStatus }
  | { type: "SET_NOTES"; notes: string }
  | { type: "TOGGLE_FLAG"; flag: HumanReview["flags"][number] }
  | { type: "INIT_FROM_AI"; evaluation: EvaluationRecord }
  | { type: "INIT_FROM_REVIEW"; review: HumanReview };

interface ReviewFormState {
  safetyScores: Record<
    string,
    { aiScore: number; humanScore: number; status: MetricScoreStatus }
  >;
  performanceScores: Record<
    string,
    { aiScore: number; humanScore: number; status: MetricScoreStatus }
  >;
  overallStatus: MetricScoreStatus;
  notes: string;
  flags: HumanReview["flags"];
  initialized: boolean;
}

function buildInitialState(): ReviewFormState {
  return {
    safetyScores: {},
    performanceScores: {},
    overallStatus: "pass",
    notes: "",
    flags: [],
    initialized: false,
  };
}

function copyAiScores(evaluation: EvaluationRecord): ReviewFormState {
  const safetyScores: ReviewFormState["safetyScores"] = {};
  for (const [key, m] of Object.entries(evaluation.safety_metrics)) {
    safetyScores[key] = {
      aiScore: m.percent,
      humanScore: m.percent,
      status: m.status,
    };
  }
  const performanceScores: ReviewFormState["performanceScores"] = {};
  for (const [key, m] of Object.entries(evaluation.performance_metrics)) {
    performanceScores[key] = {
      aiScore: m.percent,
      humanScore: m.percent,
      status: m.status,
    };
  }
  const overallStatus: MetricScoreStatus =
    evaluation.safety_status === "fail" || evaluation.performance_status === "fail"
      ? "fail"
      : evaluation.safety_status === "warn" || evaluation.performance_status === "warn"
        ? "warn"
        : "pass";

  return {
    safetyScores,
    performanceScores,
    overallStatus,
    notes: "",
    flags: [],
    initialized: true,
  };
}

function reviewFormReducer(
  state: ReviewFormState,
  action: ReviewFormAction
): ReviewFormState {
  switch (action.type) {
    case "SET_SAFETY_SCORE":
      return {
        ...state,
        safetyScores: {
          ...state.safetyScores,
          [action.metricKey]: {
            ...(state.safetyScores[action.metricKey] || {
              aiScore: 0,
              status: "pass" as MetricScoreStatus,
            }),
            humanScore: action.score,
          },
        },
      };
    case "SET_PERFORMANCE_SCORE":
      return {
        ...state,
        performanceScores: {
          ...state.performanceScores,
          [action.metricKey]: {
            ...(state.performanceScores[action.metricKey] || {
              aiScore: 0,
              status: "pass" as MetricScoreStatus,
            }),
            humanScore: action.score,
          },
        },
      };
    case "SET_SAFETY_STATUS":
      return {
        ...state,
        safetyScores: {
          ...state.safetyScores,
          [action.metricKey]: {
            ...(state.safetyScores[action.metricKey] || {
              aiScore: 0,
              humanScore: 0,
            }),
            status: action.status,
          },
        },
      };
    case "SET_PERFORMANCE_STATUS":
      return {
        ...state,
        performanceScores: {
          ...state.performanceScores,
          [action.metricKey]: {
            ...(state.performanceScores[action.metricKey] || {
              aiScore: 0,
              humanScore: 0,
            }),
            status: action.status,
          },
        },
      };
    case "SET_OVERALL_STATUS":
      return { ...state, overallStatus: action.status };
    case "SET_NOTES":
      return { ...state, notes: action.notes };
    case "TOGGLE_FLAG": {
      const exists = state.flags.includes(action.flag);
      return {
        ...state,
        flags: exists
          ? state.flags.filter((f) => f !== action.flag)
          : [...state.flags, action.flag],
      };
    }
    case "INIT_FROM_AI":
      return copyAiScores(action.evaluation);
    case "INIT_FROM_REVIEW": {
      const review = action.review;
      return {
        safetyScores: { ...review.safetyScores },
        performanceScores: { ...review.performanceScores },
        overallStatus: review.overallStatus,
        notes: review.notes,
        flags: [...review.flags],
        initialized: true,
      };
    }
    default:
      return state;
  }
}

// ---- Props ----

interface ReviewDetailPanelProps {
  open: boolean;
  evaluation: EvaluationRecord | null;
  existingReview: HumanReview | null;
  runId: string;
  isLoading: boolean;
  onClose: () => void;
  onSave: (review: HumanReview) => void;
}

// ---- Component ----

const FLAG_OPTIONS: Array<{
  value: HumanReview["flags"][number];
  label: string;
}> = [
  { value: "disputed", label: "Disputed" },
  { value: "needs_discussion", label: "Needs Discussion" },
  { value: "exemplar", label: "Exemplar" },
  { value: "reviewed_ok", label: "Reviewed OK" },
];

const SAFETY_KEYS = ["toxicity", "bias_fairness", "robustness", "compliance"];
const PERF_KEYS = [
  "relevance",
  "groundedness",
  "correctness",
  "completeness",
  "style",
  "precision",
];

export function ReviewDetailPanel({
  open,
  evaluation,
  existingReview,
  runId,
  isLoading,
  onClose,
  onSave,
}: ReviewDetailPanelProps) {
  const [state, dispatch] = useReducer(
    reviewFormReducer,
    undefined,
    buildInitialState
  );
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasUnsavedRef = useRef(false);

  // Initialize form when evaluation loads
  useEffect(() => {
    if (!evaluation) return;
    if (existingReview) {
      dispatch({ type: "INIT_FROM_REVIEW", review: existingReview });
    } else {
      dispatch({ type: "INIT_FROM_AI", evaluation });
    }
  }, [evaluation, existingReview]);

  // Auto-save debounce
  const triggerAutoSave = useCallback(() => {
    if (!evaluation || !state.initialized) return;

    if (autoSaveTimer.current) {
      clearTimeout(autoSaveTimer.current);
    }

    hasUnsavedRef.current = true;

    autoSaveTimer.current = setTimeout(() => {
      const now = new Date().toISOString();
      const review: HumanReview = {
        reviewId: existingReview?.reviewId ?? randomUUID(),
        evaluationRecordId: `${runId}::${evaluation.conversation_id || ""}::${evaluation.turn_id}`,
        runId,
        conversationId: evaluation.conversation_id || "",
        turnId: String(evaluation.turn_id),
        reviewerId: existingReview?.reviewerId ?? "human-reviewer",
        reviewStatus: "draft",
        safetyScores: { ...state.safetyScores },
        performanceScores: { ...state.performanceScores },
        overallStatus: state.overallStatus,
        notes: state.notes,
        flags: [...state.flags],
        reviewedAt: now,
        createdAt: existingReview?.createdAt ?? now,
        updatedAt: now,
      };
      onSave(review);
      hasUnsavedRef.current = false;
    }, 1500);
  }, [evaluation, state, existingReview, runId, onSave]);

  // Auto-save when form changes
  useEffect(() => {
    if (state.initialized) {
      triggerAutoSave();
    }
    return () => {
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current);
      }
    };
  }, [state, triggerAutoSave]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current);
      }
    };
  }, []);

  // Keyboard shortcuts
  const shortcuts = useMemo(
    () => [
      {
        key: "s",
        ctrlOrMeta: true,
        handler: () => handleSubmit("draft"),
        enabled: open && Boolean(evaluation) && state.initialized,
      },
      {
        key: "Enter",
        ctrlOrMeta: true,
        handler: () => handleSubmit("submitted"),
        enabled: open && Boolean(evaluation) && state.initialized,
      },
      {
        key: "Escape",
        handler: onClose,
        enabled: open,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [open, evaluation, state.initialized]
  );
  useKeyboardShortcuts(shortcuts);

  function handleSubmit(reviewStatus: "draft" | "submitted" | "approved") {
    if (!evaluation) return;

    if (autoSaveTimer.current) {
      clearTimeout(autoSaveTimer.current);
    }

    const now = new Date().toISOString();
    const review: HumanReview = {
      reviewId: existingReview?.reviewId ?? randomUUID(),
      evaluationRecordId: `${runId}::${evaluation.conversation_id || ""}::${evaluation.turn_id}`,
      runId,
      conversationId: evaluation.conversation_id || "",
      turnId: String(evaluation.turn_id),
      reviewerId: existingReview?.reviewerId ?? "human-reviewer",
      reviewStatus,
      safetyScores: { ...state.safetyScores },
      performanceScores: { ...state.performanceScores },
      overallStatus: state.overallStatus,
      notes: state.notes,
      flags: [...state.flags],
      reviewedAt: now,
      createdAt: existingReview?.createdAt ?? now,
      updatedAt: now,
    };
    onSave(review);
    hasUnsavedRef.current = false;
  }

  // ---- Render ----

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close review panel"
          className="fixed inset-0 z-40 bg-black/35 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={cn(
          "fixed top-14 right-0 bottom-0 z-50 w-full max-w-[600px] border-l border-border bg-card shadow-2xl transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex h-14 items-center justify-between border-b border-border px-4 shrink-0">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">
              Review Detail
            </div>
            {evaluation && (
              <div className="truncate text-xs text-muted-foreground font-mono">
                Turn {evaluation.turn_id}
                {evaluation.conversation_id &&
                  ` · Conv ${evaluation.conversation_id}`}
                {" · "}
                {format(parseISO(evaluation.timestamp), "MMM d HH:mm")}
              </div>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onClose}
            aria-label="Close review panel"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <ScrollArea className="h-[calc(100%-3.5rem)] p-4">
          {isLoading && (
            <div className="flex items-center gap-2 rounded-md border border-border bg-background p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading evaluation record...
            </div>
          )}

          {!isLoading && !evaluation && (
            <div className="rounded-md border border-border bg-background p-4 text-sm text-muted-foreground">
              Select a row from the Review Queue to begin reviewing.
            </div>
          )}

          {!isLoading && evaluation && state.initialized && (
            <div className="space-y-4">
              {/* Conversation Context */}
              <section className="space-y-2">
                <div className="rounded-md border border-border bg-background p-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <User className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      User Message
                    </span>
                  </div>
                  <p className="text-xs text-foreground whitespace-pre-wrap">
                    {evaluation.user_text}
                  </p>
                </div>
                <div className="rounded-md border border-border bg-background p-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Bot Response
                    </span>
                  </div>
                  <p className="text-xs text-foreground whitespace-pre-wrap">
                    {evaluation.response_text}
                  </p>
                </div>
              </section>

              {/* AI Scores Summary */}
              <section className="rounded-md border border-border bg-background p-3">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    AI Evaluation
                  </span>
                  <div className="flex items-center gap-1.5">
                    <MetricBadge status={evaluation.safety_status} />
                    <span className="text-[10px] text-muted-foreground">Safety</span>
                    <MetricBadge status={evaluation.performance_status} />
                    <span className="text-[10px] text-muted-foreground">Performance</span>
                  </div>
                </div>
              </section>

              {/* Per-Metric Scoring */}
              <div className="space-y-3">
                {/* Safety section */}
                <div>
                  <h3 className="text-xs font-semibold text-foreground mb-2 px-1">
                    Safety Metrics
                  </h3>
                  <div className="space-y-1.5">
                    {SAFETY_KEYS.map((key) => {
                      const scores = state.safetyScores[key];
                      if (!scores) return null;
                      const threshold = METRIC_THRESHOLDS[key];
                      if (!threshold) return null;
                      return (
                        <MetricScoreRow
                          key={key}
                          label={threshold.label}
                          metricKey={key}
                          description={threshold.description}
                          aiScore={scores.aiScore}
                          aiStatus={
                            evaluation.safety_metrics[
                              key as keyof typeof evaluation.safety_metrics
                            ]?.status ?? "pass"
                          }
                          humanScore={scores.humanScore}
                          humanStatus={scores.status}
                          threshold={threshold}
                          onScoreChange={(mk, score) =>
                            dispatch({
                              type: "SET_SAFETY_SCORE",
                              metricKey: mk,
                              score,
                            })
                          }
                          onStatusChange={(mk, status) =>
                            dispatch({
                              type: "SET_SAFETY_STATUS",
                              metricKey: mk,
                              status,
                            })
                          }
                        />
                      );
                    })}
                  </div>
                </div>

                {/* Performance section */}
                <div>
                  <h3 className="text-xs font-semibold text-foreground mb-2 px-1">
                    Performance Metrics
                  </h3>
                  <div className="space-y-1.5">
                    {PERF_KEYS.map((key) => {
                      const scores = state.performanceScores[key];
                      if (!scores) return null;
                      const threshold = METRIC_THRESHOLDS[key];
                      if (!threshold) return null;
                      return (
                        <MetricScoreRow
                          key={key}
                          label={threshold.label}
                          metricKey={key}
                          description={threshold.description}
                          aiScore={scores.aiScore}
                          aiStatus={
                            evaluation.performance_metrics[
                              key as keyof typeof evaluation.performance_metrics
                            ]?.status ?? "pass"
                          }
                          humanScore={scores.humanScore}
                          humanStatus={scores.status}
                          threshold={threshold}
                          onScoreChange={(mk, score) =>
                            dispatch({
                              type: "SET_PERFORMANCE_SCORE",
                              metricKey: mk,
                              score,
                            })
                          }
                          onStatusChange={(mk, status) =>
                            dispatch({
                              type: "SET_PERFORMANCE_STATUS",
                              metricKey: mk,
                              status,
                            })
                          }
                        />
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Overall Assessment */}
              <section className="space-y-3 rounded-md border border-border bg-background p-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-foreground">
                    Overall Assessment
                  </span>
                  <Select
                    value={state.overallStatus}
                    onValueChange={(v) =>
                      dispatch({
                        type: "SET_OVERALL_STATUS",
                        status: v as MetricScoreStatus,
                      })
                    }
                  >
                    <SelectTrigger className="h-7 w-[110px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pass">Pass</SelectItem>
                      <SelectItem value="warn">Warn</SelectItem>
                      <SelectItem value="fail">Fail</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Notes */}
                <div>
                  <label className="text-xs font-medium text-foreground mb-1 block">
                    Reviewer Notes
                  </label>
                  <textarea
                    value={state.notes}
                    onChange={(e) =>
                      dispatch({ type: "SET_NOTES", notes: e.target.value })
                    }
                    placeholder="Add notes about this evaluation..."
                    rows={3}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50 placeholder:text-muted-foreground resize-y"
                  />
                </div>

                {/* Flags */}
                <div>
                  <span className="text-xs font-medium text-foreground mb-1.5 block">
                    Flags
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {FLAG_OPTIONS.map(({ value, label }) => {
                      const active = state.flags.includes(value);
                      return (
                        <Button
                          key={value}
                          variant={active ? "secondary" : "outline"}
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() =>
                            dispatch({ type: "TOGGLE_FLAG", flag: value })
                          }
                        >
                          {label}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              </section>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pt-2">
                <Button
                  size="sm"
                  onClick={() => handleSubmit("submitted")}
                  className="h-8 text-xs"
                >
                  Submit Review
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleSubmit("draft")}
                  className="h-8 text-xs"
                >
                  Save Draft
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={onClose}
                  className="h-8 text-xs"
                >
                  Skip
                </Button>
              </div>
            </div>
          )}
        </ScrollArea>
      </aside>
    </>
  );
}
