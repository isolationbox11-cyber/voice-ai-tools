#!/usr/bin/env python3
"""
Async Task Processing for Voice AI Tools
Provides background processing for voice training, TTS synthesis, and analysis.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable

from cache_manager import cache_manager


@dataclass
class TaskResult:
    """Result of an async task."""

    task_id: str
    status: str  # 'pending', 'running', 'completed', 'failed'
    progress: int  # 0-100
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = None
    completed_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()


class AsyncTaskManager:
    """Manages asynchronous tasks for Voice AI Tools."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: Dict[str, TaskResult] = {}
        self._lock = threading.RLock()

        # Task configurations
        self.task_configs = {
            "voice_training": {"timeout": 600, "priority": 1},  # 10 minutes
            "tts_synthesis": {"timeout": 30, "priority": 2},  # 30 seconds
            "pdf_analysis": {"timeout": 60, "priority": 3},  # 1 minute
            "voice_analysis": {"timeout": 120, "priority": 2},  # 2 minutes
        }

    def create_task(self, task_type: str, func: Callable, *args, **kwargs) -> str:
        """Create and submit a new async task."""
        task_id = str(uuid.uuid4())

        with self._lock:
            self.tasks[task_id] = TaskResult(
                task_id=task_id, status="pending", progress=0
            )

        # Submit task to thread pool
        future = self.executor.submit(
            self._run_task, task_id, task_type, func, *args, **kwargs
        )

        return task_id

    def _run_task(self, task_id: str, task_type: str, func: Callable, *args, **kwargs):
        """Run a task with progress tracking and error handling."""
        config = self.task_configs.get(task_type, {"timeout": 300})

        try:
            # Update task status to running
            with self._lock:
                self.tasks[task_id].status = "running"

            # Check if function supports progress callback
            if (
                hasattr(func, "__code__")
                and "progress_callback" in func.__code__.co_varnames
            ):
                # Create progress callback
                def progress_callback(progress: int, message: str = ""):
                    with self._lock:
                        if task_id in self.tasks:
                            self.tasks[task_id].progress = min(max(progress, 0), 100)

                kwargs["progress_callback"] = progress_callback

            # Execute the function
            result = func(*args, **kwargs)

            # Update task with result
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id].status = "completed"
                    self.tasks[task_id].progress = 100
                    self.tasks[task_id].result = result
                    self.tasks[task_id].completed_at = time.time()

            # Cache result if applicable
            if task_type in ["tts_synthesis", "voice_analysis"]:
                cache_manager.set(task_type, result, **kwargs)

        except Exception as e:
            # Update task with error
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id].status = "failed"
                    self.tasks[task_id].error = str(e)
                    self.tasks[task_id].completed_at = time.time()

    def get_task_status(self, task_id: str) -> Optional[TaskResult]:
        """Get status of a specific task."""
        with self._lock:
            return self.tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task if it's still pending."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.status == "pending":
                task.status = "cancelled"
                task.completed_at = time.time()
                return True
            return False

    def cleanup_completed_tasks(self, max_age: int = 3600):
        """Clean up completed tasks older than max_age seconds."""
        current_time = time.time()

        with self._lock:
            tasks_to_remove = []
            for task_id, task in self.tasks.items():
                if (
                    task.status in ["completed", "failed", "cancelled"]
                    and task.completed_at
                    and current_time - task.completed_at > max_age
                ):
                    tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                del self.tasks[task_id]

    def get_task_stats(self) -> Dict[str, Any]:
        """Get statistics about running tasks."""
        with self._lock:
            stats = {
                "total_tasks": len(self.tasks),
                "pending": sum(1 for t in self.tasks.values() if t.status == "pending"),
                "running": sum(1 for t in self.tasks.values() if t.status == "running"),
                "completed": sum(
                    1 for t in self.tasks.values() if t.status == "completed"
                ),
                "failed": sum(1 for t in self.tasks.values() if t.status == "failed"),
                "cancelled": sum(
                    1 for t in self.tasks.values() if t.status == "cancelled"
                ),
                "max_workers": self.max_workers,
            }
            return stats


# Global task manager instance
task_manager = AsyncTaskManager()


# Decorator for async task functions
def async_task(task_type: str):
    """Decorator to make functions run as async tasks."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            return task_manager.create_task(task_type, func, *args, **kwargs)

        return wrapper

    return decorator


# Background cleanup thread
def start_cleanup_thread():
    """Start background thread for task cleanup."""

    def cleanup_loop():
        while True:
            time.sleep(300)  # Run every 5 minutes
            task_manager.cleanup_completed_tasks()

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    return cleanup_thread


# Start cleanup thread on module import
cleanup_thread = start_cleanup_thread()
