from types import SimpleNamespace

from server.work_attention_api import work_attention_router


class _Registry:
    def is_active(self, _device_id):
        return True

    def authorize(self, _device_id, _permission):
        return True


def test_work_attention_router_is_get_only():
    runtime = {
        "device_registry": _Registry(),
        "agent_executor": SimpleNamespace(approvals=object()),
    }
    router = work_attention_router(runtime, object())
    routes = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in router.routes
    }
    assert ("/iphone/api/work/attention", ("GET",)) in routes
    assert ("/iphone/api/work/attention/{attention_id}", ("GET",)) in routes
    assert all(set(methods) <= {"GET"} for _, methods in routes)


def test_work_attention_router_exposes_no_mutation_paths():
    runtime = {
        "device_registry": _Registry(),
        "agent_executor": SimpleNamespace(approvals=object()),
    }
    router = work_attention_router(runtime, object())
    text = "\n".join(route.path for route in router.routes).lower()
    for forbidden in ("approve", "reject", "execute", "retry", "recover", "cancel", "resume", "pause"):
        assert forbidden not in text
