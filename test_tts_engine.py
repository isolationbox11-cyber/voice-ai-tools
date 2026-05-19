import importlib
import sys
import threading
import time
import types


def test_get_client_is_thread_safe(monkeypatch):
    started = threading.Event()
    call_count_lock = threading.Lock()
    call_count = {"value": 0}

    class FakeClient:
        def __init__(self, api_key=None):
            with call_count_lock:
                call_count["value"] += 1
                current = call_count["value"]
            if current == 1:
                started.set()
                time.sleep(0.05)

    google_mod = types.ModuleType("google")
    genai_mod = types.ModuleType("google.genai")
    genai_mod.Client = FakeClient
    google_mod.genai = genai_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)

    import tts_engine
    importlib.reload(tts_engine)

    barrier = threading.Barrier(2)
    results = []

    def _worker():
        barrier.wait()
        results.append(tts_engine._get_client())

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()

    started.wait(timeout=1.0)
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert call_count["value"] == 1
    assert len(results) == 2
    assert results[0] is results[1]
