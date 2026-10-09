import base64,json,pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from updates.signed_updater import SignedUpdater,UpdateVerificationError

SOURCE_COMMIT='a'*40

def test_manifest_signature(tmp_path):
    priv=Ed25519PrivateKey.generate();pub=priv.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    updater=SignedUpdater(base64.b64encode(pub).decode(),tmp_path/'app',platform_name='linux',architecture='x64',channel='stable')
    manifest={'schema':2,'version':'v1.0.0','source_commit':SOURCE_COMMIT,'channel':'stable','artifacts':[{'name':'Vishnu-v1.0.0-linux-x64.zip','sha256':'0'*64,'size':0,'platform':'linux','architecture':'x86_64','package_type':'zip'}]}
    raw=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode();sig=base64.b64encode(priv.sign(raw)).decode()
    verified=updater.verify_manifest(raw,sig)
    assert verified['version']=='v1.0.0' and verified['schema']==2
    with pytest.raises(UpdateVerificationError):updater.verify_manifest(raw+b'x',sig)

    weak=json.dumps({'schema':1,'version':'v1.0.0','artifacts':manifest['artifacts']},sort_keys=True,separators=(',',':')).encode();weak_sig=base64.b64encode(priv.sign(weak)).decode()
    with pytest.raises(UpdateVerificationError,match='schema 2'):updater.verify_manifest(weak,weak_sig)
