#!/usr/bin/env python3
"""
Caching system for TTS results and other expensive operations.

Provides:
- Memory-based caching with TTL
- Disk-based caching for persistence
- Cache invalidation strategies
- Performance monitoring
"""

import hashlib
import json
import time
import pickle
from pathlib import Path
from typing import Optional, Any, Callable
from functools import wraps
import threading


class CacheEntry:
    """Represents a single cache entry with metadata."""

    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0
        self.last_accessed = self.created_at

    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() - self.created_at > self.ttl

    def touch(self):
        """Update last access time and increment access count."""
        self.last_accessed = time.time()
        self.access_count += 1


class MemoryCache:
    """Thread-safe memory cache with TTL support."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        """
        Initialize memory cache.

        Args:
            max_size: Maximum number of entries in cache
            default_ttl: Default time-to-live in seconds
        """
        self.cache: dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.lock = threading.RLock()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self.lock:
            entry = self.cache.get(key)

            if entry is None:
                self.stats["misses"] += 1
                return None

            if entry.is_expired():
                del self.cache[key]
                self.stats["misses"] += 1
                return None

            entry.touch()
            self.stats["hits"] += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with optional TTL."""
        with self.lock:
            if len(self.cache) >= self.max_size:
                self._evict_oldest()

            cache_ttl = ttl if ttl is not None else self.default_ttl
            self.cache[key] = CacheEntry(value, cache_ttl)

    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self.lock:
            self.cache.clear()

    def _evict_oldest(self) -> None:
        """Evict the oldest entry based on last access time."""
        if not self.cache:
            return

        oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].last_accessed)
        del self.cache[oldest_key]
        self.stats["evictions"] += 1

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items() if entry.is_expired()
            ]

            for key in expired_keys:
                del self.cache[key]

            return len(expired_keys)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self.lock:
            total = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / total if total > 0 else 0

            return {
                **self.stats,
                "size": len(self.cache),
                "hit_rate": hit_rate,
                "max_size": self.max_size,
            }


class DiskCache:
    """Disk-based cache for persistence across restarts."""

    def __init__(self, cache_dir: str = "cache", max_size_mb: int = 100):
        """
        Initialize disk cache.

        Args:
            cache_dir: Directory for cache files
            max_size_mb: Maximum cache size in megabytes
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.lock = threading.Lock()

    def _get_cache_path(self, key: str) -> Path:
        """Generate cache file path from key."""
        # Hash the key to get a safe filename
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"

    def get(self, key: str) -> Optional[Any]:
        """Get value from disk cache."""
        cache_path = self._get_cache_path(key)

        try:
            with self.lock:
                if not cache_path.exists():
                    return None

                with open(cache_path, "rb") as f:
                    data = pickle.load(f)

                # Check if expired
                if time.time() > data["expires_at"]:
                    cache_path.unlink(missing_ok=True)
                    return None

                return data["value"]
        except (pickle.PickleError, EOFError, KeyError):
            # Corrupted cache file
            with self.lock:
                cache_path.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in disk cache."""
        cache_path = self._get_cache_path(key)

        with self.lock:
            # Check if we need to clean up space
            self._cleanup_if_needed()

            data = {
                "value": value,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
            }

            with open(cache_path, "wb") as f:
                pickle.dump(data, f)

    def delete(self, key: str) -> bool:
        """Delete key from disk cache."""
        cache_path = self._get_cache_path(key)

        with self.lock:
            if cache_path.exists():
                cache_path.unlink()
                return True
            return False

    def clear(self) -> None:
        """Clear all disk cache files."""
        with self.lock:
            for cache_file in self.cache_dir.glob("*.cache"):
                cache_file.unlink()

    def _cleanup_if_needed(self) -> None:
        """Clean up old cache files if size limit exceeded."""
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.cache"))

        if total_size > self.max_size_bytes:
            # Delete oldest files until under limit
            cache_files = list(self.cache_dir.glob("*.cache"))
            cache_files.sort(key=lambda f: f.stat().st_mtime)

            for cache_file in cache_files:
                if total_size <= self.max_size_bytes * 0.8:  # Clean up to 80% of max
                    break
                total_size -= cache_file.stat().st_size
                cache_file.unlink()


def cache_result(
    memory_cache: Optional[MemoryCache] = None,
    disk_cache: Optional[DiskCache] = None,
    ttl: int = 3600,
):
    """
    Decorator to cache function results.

    Args:
        memory_cache: Memory cache instance (creates one if None)
        disk_cache: Disk cache instance (creates one if None)
        ttl: Time-to-live in seconds
    """
    if memory_cache is None:
        memory_cache = MemoryCache()
    if disk_cache is None:
        disk_cache = DiskCache()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            cache_key = f"{func.__name__}:{hashlib.sha256(json.dumps([args, kwargs], sort_keys=True).encode()).hexdigest()}"

            # Try memory cache first
            result = memory_cache.get(cache_key)
            if result is not None:
                return result

            # Try disk cache
            result = disk_cache.get(cache_key)
            if result is not None:
                memory_cache.set(cache_key, result, ttl)
                return result

            # Cache miss - call function
            result = func(*args, kwargs)

            # Store in both caches
            memory_cache.set(cache_key, result, ttl)
            disk_cache.set(cache_key, result, ttl)

            return result

        return wrapper

    return decorator


# Global cache instances
tts_cache = MemoryCache(max_size=500, default_ttl=7200)  # 2 hour TTL for TTS
lookup_cache = MemoryCache(
    max_size=1000, default_ttl=3600
)  # 1 hour TTL for OSINT lookups


if __name__ == "__main__":
    """Test caching functionality."""
    print("Testing cache system...")
    print("=" * 50)

    # Test memory cache
    cache = MemoryCache(max_size=3, default_ttl=1)

    cache.set("key1", "value1")
    cache.set("key2", "value2")

    assert cache.get("key1") == "value1"
    assert cache.get("nonexistent") is None

    print("✓ Memory cache works")

    # Test cache statistics
    stats = cache.get_stats()
    print(f"  Stats: {stats}")

    # Test expiration
    time.sleep(1.1)
    assert cache.get("key1") is None
    print("✓ Cache expiration works")

    # Test disk cache
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        disk_cache = DiskCache(cache_dir=tmpdir)

        disk_cache.set("disk_key", "disk_value")
        assert disk_cache.get("disk_key") == "disk_value"
        print("✓ Disk cache works")

    print("\nAll cache tests passed!")
