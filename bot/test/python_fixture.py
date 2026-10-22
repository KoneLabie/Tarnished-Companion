"""Ephemeral interoperability fixture. No deployment keys or disk writes."""
import base64
import hashlib
import json
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

sys.path.insert(0, sys.argv[1])
from run_package import create_package

payload = json.load(sys.stdin)
# Python float spellings deliberately differ from JSON.stringify.
payload['run']['elapsedSeconds'] = 1234.0
payload['numericInteroperability'] = [0.0, -0.0, 1e-7, 1e20 / 1e8, 2.5]
payload['unicodeInteroperability'] = 'Malenia — 剣 🗡'
# Exercise the real save-build parser using a synthetic save, never user data.
from tests.test_equipment_reference import build_slot
from tests.test_save_parser import container, BOSSES, BST
from save_reader import slot_state
data, _, _ = build_slot()
build = slot_state(container(data), 0, BOSSES, BST)['build']
build['character'] = payload['run']['character']
payload['build'] = dict(status='available', source='saved-loadout-observations', notice='Synthetic interoperability fixture',
    initial=build, final=build, truncated=False, observations=[dict(observedAt='2026-10-22T10:30:00+00:00', savedAt=None, elapsedSeconds=900.0, snapshot=build)])
signing = Ed25519PrivateKey.generate()
recipient = X25519PrivateKey.generate()
public = signing.public_key().public_bytes_raw()
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
def signer(text):
    content = (text+'\n').encode('utf-8')
    footer = dict(schemaVersion=1, algorithm='Ed25519', publicKey=base64.b64encode(public).decode(),
        fingerprint=hashlib.sha256(public).hexdigest(), payloadSha256=hashlib.sha256(content).hexdigest(),
        signature=base64.b64encode(signing.sign(b'TarnishedLineup report v1\0'+content)).decode())
    return content.decode()+'\n----- BEGIN TARNISHED LINEUP SIGNATURE -----\n'+canonical(footer)+'\n----- END TARNISHED LINEUP SIGNATURE -----\n'
package = create_package(payload, signer, recipient.public_key().public_bytes_raw())
print(json.dumps(dict(package=base64.b64encode(package).decode(), privateKey=base64.b64encode(recipient.private_bytes_raw()).decode(),
    fingerprint=hashlib.sha256(public).hexdigest(), payloadSha256=hashlib.sha256(canonical(payload).encode()).hexdigest())))
