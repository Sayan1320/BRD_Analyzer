"""
Fire-and-forget Cloud Monitoring metric writes.
All functions return immediately and silently skip if GCP_PROJECT_ID is not set.
Called via BackgroundTasks.add_task(...) in endpoint handlers.
"""
import os
import time

try:
    from google.cloud import monitoring_v3
    from google.api import metric_pb2
    from google.protobuf import timestamp_pb2
    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False


def _get_client_and_project():
    """Returns (client, project_name) or (None, None) if not configured."""
    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        return None, None
    if not _MONITORING_AVAILABLE:
        return None, None
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    return client, project_name


def _make_time_series(metric_type: str, value, labels: dict, value_type: str = "double"):
    """Build a minimal TimeSeries proto for a single data point."""
    series = monitoring_v3.TimeSeries()
    series.metric.type = f"custom.googleapis.com/{metric_type}"
    for k, v in labels.items():
        series.metric.labels[k] = v
    series.resource.type = "global"

    now = time.time()
    seconds = int(now)
    nanos = int((now - seconds) * 1e9)

    interval = monitoring_v3.TimeInterval()
    interval.end_time.seconds = seconds
    interval.end_time.nanos = nanos

    point = monitoring_v3.Point()
    point.interval = interval

    if value_type == "int":
        point.value.int64_value = int(value)
    else:
        point.value.double_value = float(value)

    series.points = [point]
    return series


def record_analyze_latency(latency_ms: float, file_type: str, model: str) -> None:
    """Record analyze endpoint latency. Req 8.5"""
    try:
        client, project_name = _get_client_and_project()
        if client is None:
            return
        series = _make_time_series(
            "analyze_latency_ms",
            latency_ms,
            {"file_type": file_type, "model": model},
        )
        client.create_time_series(name=project_name, time_series=[series])
    except Exception:
        pass


def record_tokens_per_request(tokens: int, model: str) -> None:
    """Record token usage per request. Req 8.5"""
    try:
        client, project_name = _get_client_and_project()
        if client is None:
            return
        series = _make_time_series(
            "tokens_per_request",
            tokens,
            {"model": model},
            value_type="int",
        )
        client.create_time_series(name=project_name, time_series=[series])
    except Exception:
        pass


def record_ocr_duration(duration_ms: float, file_type: str) -> None:
    """Record OCR processing duration. Req 8.5"""
    try:
        client, project_name = _get_client_and_project()
        if client is None:
            return
        series = _make_time_series(
            "ocr_duration_ms",
            duration_ms,
            {"file_type": file_type},
        )
        client.create_time_series(name=project_name, time_series=[series])
    except Exception:
        pass


def record_tts_duration(duration_ms: float, voice: str) -> None:
    """Record TTS synthesis duration. Req 8.5"""
    try:
        client, project_name = _get_client_and_project()
        if client is None:
            return
        series = _make_time_series(
            "tts_duration_ms",
            duration_ms,
            {"voice": voice},
        )
        client.create_time_series(name=project_name, time_series=[series])
    except Exception:
        pass


def record_analyze_error(error_type: str) -> None:
    """Increment analyze error counter. Req 8.5"""
    try:
        client, project_name = _get_client_and_project()
        if client is None:
            return
        series = _make_time_series(
            "analyze_error_count",
            1,
            {"error_type": error_type},
            value_type="int",
        )
        client.create_time_series(name=project_name, time_series=[series])
    except Exception:
        pass
