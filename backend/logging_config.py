import os
import structlog


def configure_logging():
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if os.getenv("LOG_FORMAT") == "pretty":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(processors=processors)
    structlog.contextvars.bind_contextvars(
        service="ai-req-summarizer", version="2.0"
    )


def get_logger(name: str):
    return structlog.get_logger(name)
