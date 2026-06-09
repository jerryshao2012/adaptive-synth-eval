"""Centralized logging configuration utility."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fields always present on a LogRecord — anything else was attached via `extra=` and is
# surfaced as a structured field by JsonFormatter.
_STD_LOGRECORD_FIELDS = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "message", "asctime", "taskName",
}

# Marks a logger as already having a CloudWatch handler attached (idempotency guard).
_CWL_ATTACHED_FLAG = "_eval_cwl_attached"

# Human-readable format shared by the console (basicConfig) and the per-run file log.
_DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Filename of the per-run log written into each run's output directory.
RUN_LOG_FILENAME = "run.log"
# Tracks the FileHandler attached for the current run so a subsequent run (same process)
# rotates to its own file instead of appending to the previous run's directory.
_RUN_FILE_HANDLER_ATTR = "_eval_run_file_handler"


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object so CloudWatch Logs Insights can query fields.

    Standard record attributes become `ts`/`level`/`logger`/`message`; anything attached via
    the `extra=` kwarg (e.g. `session_id`, `turn_id`, trace counts) is merged in as a
    top-level field. Never raises — formatting must not break logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _STD_LOGRECORD_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(value)  # keep only JSON-serializable extras as-is
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)
        return json.dumps(payload, ensure_ascii=False, default=str)


class CloudWatchLogsHandler(logging.Handler):
    """Ship log records to a CloudWatch Logs group via boto3 ``put_log_events``.

    Lazily creates the group/stream on first emit and buffers events to batch the API call.
    Every AWS interaction is wrapped so an observability failure can never break the eval
    run — on error the buffered batch is dropped and logging continues. CloudWatch caps a
    PutLogEvents call at 10k events / ~1 MB, so we flush well under that.
    """

    # Conservative thresholds (CloudWatch hard limits are 10k events / 1 MB / call).
    _MAX_BATCH = 1000
    _FLUSH_INTERVAL_S = 5.0

    def __init__(self, log_group: str, log_stream: str,
                 region: Optional[str] = None, profile: Optional[str] = None):
        super().__init__()
        self.log_group = log_group
        self.log_stream = log_stream
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._last_flush = time.monotonic()
        self._streams_ready = False
        # Build the client eagerly so a misconfiguration surfaces at setup, not mid-run.
        import boto3  # local import: only needed when CloudWatch shipping is enabled

        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        self._client = session.client("logs", region_name=region)

    def _ensure_streams(self) -> None:
        if self._streams_ready:
            return
        for create, kwargs in (
            (self._client.create_log_group, {"logGroupName": self.log_group}),
            (self._client.create_log_stream,
             {"logGroupName": self.log_group, "logStreamName": self.log_stream}),
        ):
            try:
                create(**kwargs)
            except Exception as exc:  # ResourceAlreadyExistsException is expected/benign
                if type(exc).__name__ != "ResourceAlreadyExistsException":
                    # Re-raise unexpected errors so emit()'s guard records & drops the batch.
                    raise
        self._streams_ready = True

    def _put(self, events: list[dict[str, Any]]) -> None:
        self._ensure_streams()
        # Modern CloudWatch no longer requires a sequenceToken; retry once without it if an
        # older endpoint complains about an invalid/stale token.
        try:
            self._client.put_log_events(
                logGroupName=self.log_group, logStreamName=self.log_stream,
                logEvents=events,
            )
        except Exception as exc:
            if type(exc).__name__ in (
                "InvalidSequenceTokenException", "DataAlreadyAcceptedException"
            ):
                self._client.put_log_events(
                    logGroupName=self.log_group, logStreamName=self.log_stream,
                    logEvents=events,
                )
            else:
                raise

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = {"timestamp": int(record.created * 1000),
                     "message": self.format(record)}
            with self._lock:
                self._buffer.append(event)
                due = (len(self._buffer) >= self._MAX_BATCH
                       or time.monotonic() - self._last_flush >= self._FLUSH_INTERVAL_S)
                if not due:
                    return
                batch, self._buffer = self._buffer, []
                self._last_flush = time.monotonic()
            # PutLogEvents requires chronological order within a batch.
            batch.sort(key=lambda e: e["timestamp"])
            self._put(batch)
        except Exception:  # observability must never break the caller
            self.handleError(record)

    def flush(self) -> None:
        try:
            with self._lock:
                if not self._buffer:
                    return
                batch, self._buffer = self._buffer, []
                self._last_flush = time.monotonic()
            batch.sort(key=lambda e: e["timestamp"])
            self._put(batch)
        except Exception:
            pass  # best-effort flush; never raise

    def close(self) -> None:
        self.flush()
        super().close()


def attach_cloudwatch_logs(
    logger: Optional[logging.Logger] = None,
    *,
    log_group: str,
    log_stream: Optional[str] = None,
    region: Optional[str] = None,
    profile: Optional[str] = None,
) -> Optional[logging.Logger]:
    """Attach a CloudWatchLogsHandler to ``logger`` (default: the ``adaptive_synth_eval`` tree).

    Idempotent — a second call on the same logger is a no-op. Returns the logger, or None if
    the handler could not be created (logging stays fully functional either way).
    """
    target = logger or logging.getLogger("adaptive_synth_eval")
    if getattr(target, _CWL_ATTACHED_FLAG, False):
        return target
    stream = log_stream or f"{socket.gethostname()}-{os.getpid()}-" + datetime.now(
        timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        handler = CloudWatchLogsHandler(
            log_group=log_group, log_stream=stream, region=region, profile=profile)
    except Exception:
        # Bad creds/region/missing boto3 — don't take down the run over observability setup.
        logging.getLogger(__name__).warning(
            "CloudWatch log shipping disabled: failed to init handler for group %r",
            log_group, exc_info=True)
        return None
    handler.setFormatter(JsonFormatter())
    target.addHandler(handler)
    setattr(target, _CWL_ATTACHED_FLAG, True)
    return target


def attach_run_file_log(
    run_dir: "os.PathLike[str] | str",
    *,
    logger: Optional[logging.Logger] = None,
    filename: str = RUN_LOG_FILENAME,
) -> Optional[logging.Handler]:
    """Persist the eval's log lines to ``<run_dir>/<filename>`` for the duration of a run.

    Attaches a plain-text FileHandler to the ``adaptive_synth_eval`` logger tree so the same
    records that print to the console (including the per-turn trajectory logs) are saved to
    disk alongside the run's other artifacts. If a previous run in this process attached a
    file handler, it is detached and closed first so each run writes to its own file.

    Returns the handler (or None on failure — logging stays functional either way).
    """
    target = logger or logging.getLogger("adaptive_synth_eval")
    # Rotate off any handler from a prior run so we don't keep writing to the old run_dir.
    previous = getattr(target, _RUN_FILE_HANDLER_ATTR, None)
    if previous is not None:
        target.removeHandler(previous)
        try:
            previous.close()
        except Exception:
            pass
        setattr(target, _RUN_FILE_HANDLER_ATTR, None)
    try:
        from pathlib import Path

        path = Path(run_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except Exception:
        logging.getLogger(__name__).warning(
            "run file log disabled: could not open %s/%s", run_dir, filename, exc_info=True)
        return None
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT))
    target.addHandler(handler)
    setattr(target, _RUN_FILE_HANDLER_ATTR, handler)
    return handler


def setup_logger(
        name: Optional[str] = None,
        level: Optional[str] = None,
        format_string: Optional[str] = None,
) -> logging.Logger:
    """
    Setup and configure a logger with centralized configuration.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
              Defaults to LOG_LEVEL env var or "INFO"
        format_string: Custom log format string
                      Defaults to standard format with timestamp
    
    Returns:
        Configured logger instance
    
    Example:
        from logger_utils import setup_logger
        logger = setup_logger(__name__)
        logger.info("Application started")
    """
    # Get log level from parameter, env var, or default to INFO
    log_level = level or os.getenv("LOG_LEVEL", "INFO").upper()

    # Default format if not provided
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger only once
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format=format_string,  # type: ignore[arg-type]
            datefmt="%Y-%m-%d %H:%M:%S"
        )

    # Optional: ship eval-client logs directly to a dedicated CloudWatch log group (kept
    # separate from the target server's logs). Enabled only when EVAL_CWL_LOG_GROUP is set,
    # so local runs are unaffected. Attached once to the adaptive_synth_eval logger tree.
    cwl_group = os.getenv("EVAL_CWL_LOG_GROUP")
    if cwl_group:
        attach_cloudwatch_logs(
            log_group=cwl_group,
            log_stream=os.getenv("EVAL_CWL_LOG_STREAM"),
            region=os.getenv("EVAL_CWL_REGION")
            or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            profile=os.getenv("EVAL_AWS_PROFILE"),
        )

    # Get logger for the specific module
    logger = logging.getLogger(name)

    return logger


def get_log_level_from_env(default: str = "INFO") -> int:
    """
    Get numeric log level from environment variable.
    
    Args:
        default: Default level string if env var not set
    
    Returns:
        Numeric logging level constant
    """
    level_str = os.getenv("LOG_LEVEL", default).upper()
    return getattr(logging, level_str, logging.INFO)
