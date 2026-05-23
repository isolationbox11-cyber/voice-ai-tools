#!/usr/bin/env python3
"""
Cache Manager for Voice AI Tools
Provides intelligent caching for TTS responses, voice models, and analysis results.
"""

import json
import hashlib
import time
from typing import Optional, Dict, Any
from pathlib import Path
import threading
from dataclasses import dataclass, asdict
from contextlib import suppress


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    data: Any
    timestamp: float
    ttl: int  # Time to live in seconds
    content_type: str = "application/octet-stream"

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return time.time() - self.timestamp > self.ttl


class CacheManager:
    """Thread-safe cache manager for Voice AI Tools."""

    def __init__(self, cache_dir: str = "cache", default_ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.default_ttl = default_ttl
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

        # Cache configurations
        self.cache_configs = {
            "tts_response": {"ttl": 86400, "max_size": 100},  # 24 hours
            "voice_model": {"ttl": 604800, "max_size": 50},  # 1 week
            "analysis_result": {"ttl": 3600, "max_size": 200},  # 1 hour
            "metadata": {"ttl": 300, "max_size": 1000},  # 5 minutes
        }

    def _generate_key(self, prefix: str, **kwargs) -> str:
        """Generate cache key from parameters."""
        key_data = f"{prefix}:{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """Get file path for cache key."""
        return self.cache_dir / f"{key}.cache"

    def _cleanup_memory_cache(self):
        """Clean up expired entries from memory cache."""
        expired_keys = [
            key for key, entry in self._memory_cache.items() if entry.is_expired()
        ]
        for key in expired_keys:
            del self._memory_cache[key]

    def get(self, cache_type: str, **kwargs) -> Optional[Any]:
        """Get cached item."""
        key = self._generate_key(cache_type, **kwargs)

        with self._lock:
            # Check memory cache first
            if key in self._memory_cache:
                entry = self._memory_cache[key]
                if not entry.is_expired():
                    return entry.data
                else:
                    del self._memory_cache[key]

            # Check disk cache
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                try:
                    with open(cache_path, "rb") as f:
                        data = json.load(f)
                    entry = CacheEntry(**data)

                    if not entry.is_expired():
                        # Restore to memory cache
                        self._memory_cache[key] = entry
                        return entry.data
                    else:
                        # Remove expired file
                        cache_path.unlink()
                except Exception:
                    # Remove corrupted cache file
                    cache_path.unlink(missing_ok=True)

        return None

    def set(
        self,
        cache_type: str,
        data: Any,
        content_type: str = "application/octet-stream",
        **kwargs,
    ):
        """Set cache item."""
        key = self._generate_key(cache_type, **kwargs)
        config = self.cache_configs.get(
            cache_type, {"ttl": self.default_ttl, "max_size": 100}
        )

        entry = CacheEntry(
            data=data,
            timestamp=time.time(),
            ttl=config["ttl"],
            content_type=content_type,
        )

        with self._lock:
            # Check memory cache size
            if len(self._memory_cache) >= config["max_size"]:
                self._cleanup_memory_cache()
                if len(self._memory_cache) >= config["max_size"]:
                    oldest_key = min(
                        self._memory_cache.keys(),
                        key=lambda k: self._memory_cache[k].timestamp,
                    )
                    del self._memory_cache[oldest_key]

            # Add to memory cache
            self._memory_cache[key] = entry

            # Save to disk cache
            cache_path = self._get_cache_path(key)
            with suppress(Exception):
                with open(cache_path, "w") as f:
                    json.dump(asdict(entry), f)

    def invalidate(self, cache_type: str, **kwargs):
        """Invalidate specific cache entry."""
        key = self._generate_key(cache_type, **kwargs)

        with self._lock:
            # Remove from memory cache
            self._memory_cache.pop(key, None)

            # Remove from disk cache
            cache_path = self._get_cache_path(key)
            cache_path.unlink(missing_ok=True)

    def clear_cache_type(self, cache_type: str):
        """Clear all entries of a specific type."""
        prefix = cache_type

        with self._lock:
            # Clear memory cache
            keys_to_remove = [
                key
                for key in self._memory_cache.keys()
                if key.startswith(hashlib.md5(f"{prefix}:".encode()).hexdigest()[:8])
            ]
            for key in keys_to_remove:
                del self._memory_cache[key]

            # Clear disk cache
            for cache_file in self.cache_dir.glob("*.cache"):
                with suppress(Exception):
                    with open(cache_file, "r") as f:
                        data = json.load(f)
                    if cache_type in data.get("data", {}):
                        cache_file.unlink()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            memory_size = len(self._memory_cache)
            expired_count = sum(
                1 for entry in self._memory_cache.values() if entry.is_expired()
            )

            # Count disk cache files
            disk_size = len(list(self.cache_dir.glob("*.cache")))

            return {
                "memory_cache_size": memory_size,
                "disk_cache_size": disk_size,
                "expired_entries": expired_count,
                "cache_directory": str(self.cache_dir),
            }


# Global cache instance
cache_manager = CacheManager()
