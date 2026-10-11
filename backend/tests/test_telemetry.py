from types import SimpleNamespace

from app.services.telemetry import configure_telemetry


def test_telemetry_is_noop_when_disabled():
    settings = SimpleNamespace(otel_enabled=False)

    assert configure_telemetry(object(), settings, object()) is False


def test_telemetry_reports_missing_optional_dependencies(monkeypatch):
    import builtins
    original_import = builtins.__import__

    def import_without_otel(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_otel)
    settings = SimpleNamespace(otel_enabled=True)

    try:
        configure_telemetry(object(), settings, object())
    except RuntimeError as exc:
        assert "dependencies are not installed" in str(exc)
    else:
        raise AssertionError("enabled telemetry should fail clearly without its dependencies")
