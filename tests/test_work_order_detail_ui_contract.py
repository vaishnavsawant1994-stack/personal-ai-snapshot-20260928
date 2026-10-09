from pathlib import Path


def test_work_order_detail_is_read_only_and_uses_authoritative_aggregate():
    api = Path('server/work_order_detail_api.py').read_text()
    ui = Path('pwa/workorder-detail.js').read_text()
    loader = Path('pwa/home-chat-redesign.js').read_text()
    sw = Path('pwa/sw.js').read_text()

    assert '@router.get("/{project_id}/work/{plan_id}/orders/{task_id}")' in api
    assert '"read_only": True' in api
    for authority in ('existing_p10_p6_runtime','approval_manager','evidence_store','claim_gate','deterministic_reviewer','deterministic_completion_judge','recovery_authority'):
        assert authority in api
    assert '@router.post' not in api
    assert '@router.put' not in api
    assert '@router.delete' not in api

    assert 'authority:\'read_only_projection\'' in ui
    assert '/orders/${encodeURIComponent(taskId)}' in ui
    assert "method:'POST'" not in ui
    assert 'method:"POST"' not in ui
    assert "method:'PUT'" not in ui
    assert "method:'DELETE'" not in ui
    assert 'verified=true' not in ui.lower()
    assert 'completed=true' not in ui.lower()
    assert '@media(max-width:760px)' in ui

    assert '/iphone/workorder-detail.js' in loader
    assert "detail.onload=loadGlobal" in loader
    assert "'/iphone/workorder-detail.js'" in sw
    assert "url.pathname.startsWith('/iphone/api/')" in sw
