import base64,sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from updates import release_sign
from updates.release_verify import verify

SOURCE_COMMIT='a'*40

def test_release_manifest_sign_verify_and_tamper_detection(tmp_path,monkeypatch):
    key=Ed25519PrivateKey.generate();raw=key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption());public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    artifact=tmp_path/'Vishnu-v1.0.0-windows-x64.msi';artifact.write_bytes(b'installer-bytes')
    manifest=tmp_path/'manifest.json'
    monkeypatch.setenv('PERSONAL_AI_RELEASE_PRIVATE_KEY_B64',base64.b64encode(raw).decode())
    monkeypatch.setattr(sys,'argv',['release_sign.py','--version','v1.0.0','--source-commit',SOURCE_COMMIT,'--channel','stable','--output',str(manifest),str(artifact)])
    release_sign.main()
    parsed=verify(manifest,str(manifest)+'.sig',base64.b64encode(public).decode(),tmp_path,expected_version='v1.0.0',expected_source_commit=SOURCE_COMMIT,expected_channel='stable',expected_platform='windows',expected_architecture='x64')
    assert parsed['version']=='v1.0.0' and parsed['schema']==2
    assert parsed['source_commit']==SOURCE_COMMIT and parsed['channel']=='stable'
    artifact.write_bytes(b'tampered')
    try:verify(manifest,str(manifest)+'.sig',base64.b64encode(public).decode(),tmp_path)
    except ValueError:pass
    else:raise AssertionError('tampered installer unexpectedly verified')
