"""Recipient configuration and isolated encrypted walkthrough samples."""
import base64
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from record_integrity import REPORT_BEGIN, REPORT_END, REPORT_DOMAIN
from run_package import create_package, recipient_key_id

MIME = 'application/vnd.tarnished-companion.run+json'


def load_recipient(path):
    try:
        path = Path(path)
        if path.stat().st_size > 4096:
            raise ValueError('Oversized recipient configuration.')
        config = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(config, dict) or type(config.get('schemaVersion')) is not int
                or config['schemaVersion'] != 1 or config.get('algorithm') != 'X25519'
                or 'privateKey' in config):
            raise ValueError('Invalid public recipient configuration.')
        public = base64.b64decode(config['publicKey'], validate=True)
        if len(public) != 32 or config.get('fingerprint') != recipient_key_id(public):
            raise ValueError('Invalid recipient fingerprint.')
        return public
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None


def export_status(public):
    return dict(extension='.tlrun', encrypted=public is not None, configured=public is not None,
                notice='Encrypted run package with signed timings and saved character loadouts.' if public else
                       'Report export is unavailable until the verifier public key is configured.')


def sample_package(public, state):
    """Ephemeral demo signer; never uses the player's signing identity or records."""
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    b64 = lambda raw: base64.b64encode(raw).decode('ascii')
    def signer(text):
        text = text if text.endswith('\n') else text + '\n'
        raw = text.encode('utf-8')
        # LocalIntegrity uses this exact envelope. This key is deliberately
        # untrusted and the decrypted payload has simulation=True.
        meta = dict(schemaVersion=1, algorithm='Ed25519', publicKey=b64(pub),
                    fingerprint=hashlib.sha256(pub).hexdigest(), payloadSha256=hashlib.sha256(raw).hexdigest(),
                    signature=b64(key.sign(REPORT_DOMAIN + raw)))
        return text + REPORT_BEGIN + json.dumps(meta, sort_keys=True, separators=(',', ':')) + REPORT_END
    payload = dict(schemaVersion=1, format='tarnished-run', simulation=True,
                   exportedAt=datetime.now(timezone.utc).isoformat(),
                   run=state['speedrun'], attempts=state['bossAttempts'],
                   build=dict(status='unavailable', notice='Walkthrough sample; no player save was read.'),
                   reportText='SIMULATED PREVIEW — NOT A RUN RECORD', application=dict(kind='Walkthrough simulation'))
    return create_package(payload, signer, public)
