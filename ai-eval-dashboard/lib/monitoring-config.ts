import type {
  EvalRunParameters,
  MonitoringAction,
  MonitoringStartRequest,
  SamplingStrategy,
} from "@/types/evaluation";

const MONITORING_ACTIONS: readonly MonitoringAction[] = [
  "start",
  "continue",
  "reevaluate",
];
const SAMPLING_STRATEGIES: readonly SamplingStrategy[] = [
  "all",
  "random",
  "systematic",
];
const SUPPORTED_REQUEST_FIELDS = new Set([
  "runId",
  "action",
  "samplingStrategy",
  "sampleSize",
  "intervalMinutes",
  "maxWindows",
]);

export const DEFAULT_MONITORING_PARAMETERS: EvalRunParameters = {
  samplingStrategy: "all",
  sampleSize: 1000,
  intervalMinutes: 60,
  maxWindows: null,
};

export class MonitoringRequestValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MonitoringRequestValidationError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isMonitoringAction(value: unknown): value is MonitoringAction {
  return (
    typeof value === "string" &&
    MONITORING_ACTIONS.includes(value as MonitoringAction)
  );
}

function isSamplingStrategy(value: unknown): value is SamplingStrategy {
  return (
    typeof value === "string" &&
    SAMPLING_STRATEGIES.includes(value as SamplingStrategy)
  );
}

export function normalizeMonitoringParameters(
  state: unknown
): EvalRunParameters {
  const record = isObject(state) ? state : {};

  return {
    samplingStrategy: isSamplingStrategy(record.sampling_strategy)
      ? record.sampling_strategy
      : DEFAULT_MONITORING_PARAMETERS.samplingStrategy,
    sampleSize: isPositiveInteger(record.sample_size)
      ? record.sample_size
      : DEFAULT_MONITORING_PARAMETERS.sampleSize,
    intervalMinutes: isPositiveInteger(record.interval_minutes)
      ? record.interval_minutes
      : DEFAULT_MONITORING_PARAMETERS.intervalMinutes,
    maxWindows:
      record.max_windows === null || isPositiveInteger(record.max_windows)
        ? record.max_windows
        : DEFAULT_MONITORING_PARAMETERS.maxWindows,
  };
}

function parseRunId(value: unknown): string {
  if (typeof value !== "string") {
    throw new MonitoringRequestValidationError("runId must be a string.");
  }

  const hasControlCharacters = /[\u0000-\u001f\u007f-\u009f]/u.test(value);
  const runId = value.trim();
  if (
    hasControlCharacters ||
    !runId ||
    runId === "." ||
    runId === ".." ||
    runId.includes("/") ||
    runId.includes("\\")
  ) {
    throw new MonitoringRequestValidationError(
      "runId must be one safe path segment."
    );
  }

  return runId;
}

function parsePositiveInteger(
  value: unknown,
  field: "sampleSize" | "intervalMinutes" | "maxWindows"
): number {
  if (!isPositiveInteger(value)) {
    throw new MonitoringRequestValidationError(
      `${field} must be a positive integer.`
    );
  }
  return value;
}

export function parseMonitoringStartRequest(
  value: unknown
): MonitoringStartRequest {
  if (!isObject(value)) {
    throw new MonitoringRequestValidationError(
      "Request body must be an object."
    );
  }

  const unsupportedField = Object.keys(value).find(
    (field) => !SUPPORTED_REQUEST_FIELDS.has(field)
  );
  if (unsupportedField) {
    throw new MonitoringRequestValidationError(
      `Unsupported request field: ${unsupportedField}.`
    );
  }

  const runId = parseRunId(value.runId);
  if (!isMonitoringAction(value.action)) {
    throw new MonitoringRequestValidationError(
      "action must be 'start', 'continue', or 'reevaluate'."
    );
  }
  if (
    value.samplingStrategy !== undefined &&
    !isSamplingStrategy(value.samplingStrategy)
  ) {
    throw new MonitoringRequestValidationError(
      "samplingStrategy must be 'all', 'random', or 'systematic'."
    );
  }

  const samplingStrategy =
    value.samplingStrategy ?? DEFAULT_MONITORING_PARAMETERS.samplingStrategy;
  const sampleSize =
    value.sampleSize === undefined
      ? DEFAULT_MONITORING_PARAMETERS.sampleSize
      : parsePositiveInteger(value.sampleSize, "sampleSize");
  const intervalMinutes =
    value.intervalMinutes === undefined
      ? DEFAULT_MONITORING_PARAMETERS.intervalMinutes
      : parsePositiveInteger(value.intervalMinutes, "intervalMinutes");
  const maxWindows =
    value.maxWindows === undefined || value.maxWindows === null
      ? DEFAULT_MONITORING_PARAMETERS.maxWindows
      : parsePositiveInteger(value.maxWindows, "maxWindows");

  return {
    runId,
    action: value.action,
    samplingStrategy,
    sampleSize,
    intervalMinutes,
    maxWindows,
  };
}

export function buildMonitoringArgs(
  request: MonitoringStartRequest,
  relativeRunFolder: string
): string[] {
  const args = [
    "run",
    "ase",
    "monitor",
    "run",
    "--run-folder",
    relativeRunFolder,
    "--sampling-strategy",
    request.samplingStrategy,
  ];

  if (request.samplingStrategy !== "all") {
    args.push("--sample-size", String(request.sampleSize));
  }
  args.push("--interval-minutes", String(request.intervalMinutes));
  if (request.maxWindows !== null) {
    args.push("--max-windows", String(request.maxWindows));
  }
  args.push(
    "--incomplete-run-action",
    request.action === "start" ? "restart" : "resume"
  );
  if (request.action === "reevaluate") {
    args.push("--rescan");
  }

  return args;
}
