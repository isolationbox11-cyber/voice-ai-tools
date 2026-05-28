#!/usr/bin/env python3
"""
Structured logging and metrics collection for production monitoring.

Provides:
- JSON-formatted structured logging
- Request/response metrics collection
- Performance monitoring
- Error tracking
- Custom metrics support
"""

import json
import logging
import time
import threading
from typing import Any, Dict, Optional, Callable
from functools import wraps
from datetime import datetime
from contextlib import contextmanager


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add custom attributes if present
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "lineno", "funcName", "created",
                "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "message", "exc_info", "exc_text"
            }:
                log_data[key] = value

        return json.dumps(log_data)


class MetricsCollector:
    """Thread-safe metrics collector for application monitoring."""

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics: Dict[str, Any] = {}
        self.lock = threading.Lock()
        self.start_time = time.time()

    def increment(self, metric_name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        with self.lock:
            if metric_name not in self.metrics:
                self.metrics[metric_name] = 0
            self.metrics[metric_name] += value

    def timing(self, metric_name: str, duration: float) -> None:
        """Record a timing metric in seconds."""
        with self.lock:
            key = f"{metric_name}_timing"
            if key not in self.metrics:
                self.metrics[key] = []
            self.metrics[key].append(duration)

    def gauge(self, metric_name: str, value: float) -> None:
        """Set a gauge metric value."""
        with self.lock:
            self.metrics[metric_name] = value

    def get_metrics(self) -> Dict[str, Any]:
        """Get all current metrics."""
        with self.lock:
            result = {
                "uptime_seconds": time.time() - self.start_time,
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Calculate statistics for timing metrics
            for key, value in self.metrics.items():
                if isinstance(value, list) and all(isinstance(x, (int, float)) for x in value):
                    if len(value) > 0:
                        result[f"{key}_avg"] = sum(value) / len(value)
                        result[f"{key}_min"] = min(value)
                        result[f"{key}_max"] = max(value)
                        result[f"{key}_count"] = len(value)
                else:
                    result[key] = value

            return result

    def reset(self) -> None:
        """Reset all metrics."""
        with self.lock:
            self.metrics.clear()


class RequestMetrics:
    """Track request/response metrics for API endpoints."""

    def __init__(self):
        """Initialize request metrics."""
        self.metrics = MetricsCollector()
        self.lock = threading.Lock()
        self.request_data: Dict[str, Any] = {}

    def track_request(self, endpoint: str, method: str) -> None:
        """Track a request start."""
        request_id = f"{endpoint}_{method}_{time.time()}"
        with self.lock:
            self.request_data[request_id] = {
                "endpoint": endpoint,
                "method": method,
                "start_time": time.time(),
            }
        return request_id

    def track_response(self, request_id: str, status_code: int) -> None:
        """Track a response completion."""
        with self.lock:
            if request_id in self.request_data:
                request_info = self.request_data[request_id]
                duration = time.time() - request_info["start_time"]

                # Update metrics
                endpoint = request_info["endpoint"]
                self.metrics.increment(f"requests_{endpoint}")
                self.metrics.increment(f"requests_total")
                
                if status_code >= 400:
                    self.metrics.increment(f"errors_{endpoint}")
                    self.metrics.increment("errors_total")
                
                self.metrics.timing(f"duration_{endpoint}", duration)
                self.metrics.timing("duration_all", duration)

                # Clean up
                del self.request_data[request_id]

    def get_summary(self) -> Dict[str, Any]:
        """Get request metrics summary."""
        return self.metrics.get_metrics()


@contextmanager
def track_function_call(metric_name: str, metrics: MetricsCollector):
    """Context manager to track function call duration."""
    start_time = time.time()
    try:
        yield
        duration = time.time() - start_time
        metrics.timing(metric_name, duration)
        metrics.increment(f"{metric_name}_success")
    except Exception as e:
        duration = time.time() - start_time
        metrics.timing(metric_name, duration)
        metrics.increment(f"{metric_name}_error")
        raise


def log_function_call(metric_name: str, metrics: MetricsCollector):
    """Decorator to log and track function calls."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            with track_function_call(metric_name, metrics):
                logger = logging.getLogger(func.__module__)
                logger.info(
                    f"Calling function: {func.__name__}",
                    extra={"function": func.__name__, "metric": metric_name}
                )
                return func(*args, **kwargs)
        return wrapper
    return decorator


def setup_structured_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    Setup structured JSON logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path

    Returns:
        Configured logger instance
    """
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler with JSON formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)

    return logging.getLogger(__name__)


# Global metrics instances
request_metrics = RequestMetrics()
app_metrics = MetricsCollector()


def get_log_context() -> Dict[str, Any]:
    """Get current logging context for adding to logs."""
    return {
        "request_id": getattr(request_metrics, "current_request_id", None),
        "uptime": request_metrics.metrics.get_metrics().get("uptime_seconds"),
        "timestamp": datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    """Test structured logging and metrics."""
    print("Testing structured logging and metrics...")
    print("=" * 50)
    
    # Setup logging
    setup_structured_logging("INFO")
    logger = logging.getLogger(__name__)
    
    # Test JSON logging
    logger.info("Test info message", extra={"custom_field": "custom_value"})
    logger.warning("Test warning message")
    logger.error("Test error message")
    
    print("✓ Structured logging works")
    
    # Test metrics
    metrics = MetricsCollector()
    metrics.increment("test_counter", 5)
    metrics.timing("test_timing", 1.5)
    metrics.gauge("test_gauge", 42.0)
    
    metric_data = metrics.get_metrics()
    print(f"✓ Metrics collection works: {json.dumps(metric_data, indent=2)}")
    
    # Test request metrics
    request_metrics.track_request("/test", "GET")
    time.sleep(0.1)
    request_metrics.track_response("test_request_id", 200)
    
    print(f"✓ Request metrics work: {json.dumps(request_metrics.get_summary(), indent=2)}")
    
    print("\nAll logging and metrics tests passed!")