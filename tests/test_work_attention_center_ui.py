from pathlib import Path


def test_attention_center_is_read_only_and_uses_existing_authorities():
    source = Path('pwa/work-attention-center.js').read_text()
    loader = Path('pwa/home-chat-redesign.js').read_text()
    sw = Path('pwa/sw.js').read_text()

    assert "authority:'read_only_projection'" in source
    assert "/iphone/api/work/attention?limit=200" in source
    for label in ('All','Approvals','Recovery','Blocked','Verification','Review','Claims'):
        assert f"label:'{label}'" in source
    for kind in ('approval_required','recovery_required','blocked','verification_failed','review_failed','claim_unsupported'):
        assert kind in source
    assert "item.deep_link" in source
    assert "item.authority" in source
    assert "item.reason" in source
    assert "item.project_name" in source
    assert "item.work_order_title" in source
    assert "method:'POST'" not in source
    assert 'method:"POST"' not in source
    assert "method:'PUT'" not in source
    assert "method:'DELETE'" not in source
    assert 'approve(' not in source.lower()
    assert 'retry(' not in source.lower()
    assert 'recover(' not in source.lower()

    assert '/iphone/work-attention-center.js' in loader
    assert 'global.onload=loadAttentionCenter' in loader
    assert "'/iphone/work-attention-center.js'" in sw
    assert "url.pathname.startsWith('/iphone/api/')" in sw
