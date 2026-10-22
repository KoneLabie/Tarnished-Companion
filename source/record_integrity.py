"""Local tamper evidence for timing records and portable Ed25519 TXT reports.

The current Windows user owns this signer. A valid signature proves possession
of its key, not honest gameplay or acceptance by a speedrun leaderboard.
Call verify before an authorized transaction, then seal after its writes.
"""
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


REPORT_BEGIN = '\n----- BEGIN TARNISHED LINEUP SIGNATURE -----\n'
REPORT_END = '\n----- END TARNISHED LINEUP SIGNATURE -----\n'
REPORT_DOMAIN = b'TarnishedLineup report v1\0'
MANIFEST_DOMAIN = b'TarnishedLineup records v1\0'
KEY_FILE = 'record-integrity-key.json'
MANIFEST_FILE = 'record-integrity.json'
RECOVERY_FILE = 'record-recovery.json'
RECOVERY_DOMAIN = b'TarnishedLineup recovery v1\0'
MAX_RECOVERY_BYTES = 64 * 1024 * 1024
CLEANUP_NOTICE = 'Signed records are safe; recovery checkpoint cleanup is deferred until the file is available.'
TIMING_FILES = ('external-run.json', 'boss-attempts.json', 'run-policy.json', 'run-state.json')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _b64(value):
    return base64.b64encode(value).decode('ascii')


def _decode(value, length=None):
    if not isinstance(value, str):
        raise ValueError('Invalid protected record encoding.')
    decoded = base64.b64decode(value, validate=True)
    if length is not None and len(decoded) != length:
        raise ValueError('Invalid protected record length.')
    return decoded


def _digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Timing records must be regular files inside the data directory.')
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


class WindowsProtector:
    """DPAPI current-user protection, with no machine-wide or UI fallback."""
    label = 'Windows-DPAPI-current-user'

    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows DPAPI is required to protect the local signing key.')
        self.crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)

        class Blob(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        self.Blob = Blob
        self.crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
            ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt.CryptProtectData.restype = wintypes.BOOL
        self.crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p

    def _transform(self, data, protect):
        array = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source = self.Blob(len(data), array)
        destination = self.Blob()
        if protect:
            success = self.crypt.CryptProtectData(ctypes.byref(source), 'Tarnished Companion signing key',
                None, None, None, 1, ctypes.byref(destination))
        else:
            success = self.crypt.CryptUnprotectData(ctypes.byref(source), None,
                None, None, None, 1, ctypes.byref(destination))
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(destination.data, destination.length)
        finally:
            self.kernel.LocalFree(destination.data)

    def protect(self, data):
        return self._transform(data, True)

    def unprotect(self, data):
        return self._transform(data, False)


class LocalIntegrity:
    """Fail closed on missing keys, unsigned legacy records, or modified files.

    ``protector`` is an injectable protect/unprotect object for isolated tests.
    Production callers must use the default WindowsProtector. Once tainted,
    this instance and its protected key state cannot reseal or sign records.
    A caller must preserve the affected directory for review, not erase it.
    """
    def __init__(self, data_dir, protector=None, recover_interrupted=False):
        self.directory = Path(data_dir)
        self.key_path = self.directory / KEY_FILE
        self.manifest_path = self.directory / MANIFEST_FILE
        self.notice = ''
        self.public_fingerprint = None
        self.tainted = False
        self._private = None
        self._public = None
        self._key_state = None
        self._protector = None
        self._manifest_digest = None
        self._key_digest = None
        self._verified_transaction = False
        self.recovery_path = self.directory / RECOVERY_FILE
        self.recovered = False
        self.recovery_notice = ''
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._protector = protector if protector is not None else WindowsProtector()
            existing = self._files()
            key_exists = self.key_path.exists()
            manifest_exists = self.manifest_path.exists()
            if key_exists:
                envelope = self._read_json(self.key_path, 1024 * 1024)
                if (not isinstance(envelope, dict) or set(envelope) != {'schemaVersion', 'protection', 'protected'}
                        or envelope['schemaVersion'] != 1
                        or envelope['protection'] != getattr(self._protector, 'label', 'Injected-test-protector')):
                    raise ValueError('The signing key protection envelope is invalid.')
                state = json.loads(self._protector.unprotect(_decode(envelope['protected'])).decode('utf-8'))
                if (not isinstance(state, dict) or set(state) != {'schemaVersion', 'privateKey', 'tainted', 'reason'}
                        or state['schemaVersion'] != 1 or type(state['tainted']) is not bool
                        or not isinstance(state['reason'], str)):
                    raise ValueError('The protected signing key state is invalid.')
                self._key_state = state
                self._private = Ed25519PrivateKey.from_private_bytes(_decode(state['privateKey'], 32))
                self._identity()
                self._key_digest = _digest(self.key_path)
                if state['tainted']:
                    self.tainted = True
                    self.notice = state['reason'] or 'Local timing record integrity was previously lost.'
                    return
                if not manifest_exists:
                    self._fail('The signed timing manifest is missing. Existing records cannot be trusted.')
                    return
                self._manifest_digest = _digest(self.manifest_path)
                if recover_interrupted and self.recovery_path.exists():
                    self._recover_checkpoint()
                self.verify()
            elif manifest_exists or existing:
                self._fail('Timing records exist without their protected signing key and manifest. Preserve them; unsigned history cannot be authenticated.')
            else:
                self._private = Ed25519PrivateKey.generate()
                self._identity()
                seed = self._private.private_bytes(serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw, serialization.NoEncryption())
                self._key_state = dict(schemaVersion=1, privateKey=_b64(seed), tainted=False, reason='')
                self._write_key()
                self._write_manifest({})
                self._verified_transaction = True
        except Exception:
            # Key material and DPAPI details are deliberately never logged.
            self._fail('Local signing could not initialize. Timing exports are blocked until integrity is restored.')

    def _identity(self):
        self._public = self._private.public_key().public_bytes(serialization.Encoding.Raw,
                                                              serialization.PublicFormat.Raw)
        self.public_fingerprint = hashlib.sha256(self._public).hexdigest()

    @staticmethod
    def _read_json(path, maximum=16 * 1024 * 1024):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise ValueError('Invalid integrity metadata file.')
        return json.loads(path.read_text(encoding='utf-8'))

    def _files(self):
        files = {}
        for name in TIMING_FILES:
            path = self.directory / name
            if path.exists() or path.is_symlink():
                files[name] = _digest(path)
        archives = self.directory / 'run-records'
        if archives.is_symlink():
            raise ValueError('Archived timing records must remain inside the data directory.')
        if archives.exists():
            if not archives.is_dir():
                raise ValueError('The timing archive must be a directory.')
            for path in archives.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Timing archive links are not supported.')
                if path.suffix.casefold() == '.json':
                    files[path.relative_to(self.directory).as_posix()] = _digest(path)
        return dict(sorted(files.items()))

    @staticmethod
    def _atomic(path, content):
        temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_key(self):
        protected = self._protector.protect(_canonical(self._key_state))
        envelope = dict(schemaVersion=1, protection=getattr(self._protector, 'label', 'Injected-test-protector'),
                        protected=_b64(protected))
        self._atomic(self.key_path, _canonical(envelope))
        self._key_digest = _digest(self.key_path)

    def _write_manifest(self, files):
        payload = dict(schemaVersion=1, fingerprint=self.public_fingerprint, files=files)
        envelope = dict(payload=payload, signature=_b64(self._private.sign(MANIFEST_DOMAIN + _canonical(payload))))
        self._atomic(self.manifest_path, _canonical(envelope))
        self._manifest_digest = _digest(self.manifest_path)

    def _fail(self, reason):
        self.tainted = True
        self._verified_transaction = False
        self.notice = reason
        if self._key_state is not None:
            self._key_state.update(tainted=True, reason=reason)
            try:
                self._write_key()
            except Exception:
                self.notice += ' The blocked state could not be persisted; preserve this directory for review.'
        return False

    def _controls_unchanged(self):
        return (_digest(self.key_path) == self._key_digest
                and _digest(self.manifest_path) == self._manifest_digest)

    def verify(self):
        """Verify the signed manifest and all tracked files before mutation."""
        self._verified_transaction = False
        if self.tainted or self._private is None:
            return False
        try:
            if not self._controls_unchanged():
                return self._fail('Signing metadata changed outside an authorized update. Timing export is blocked.')
            envelope = self._read_json(self.manifest_path)
            if not isinstance(envelope, dict) or set(envelope) != {'payload', 'signature'}:
                raise ValueError('Invalid manifest envelope.')
            payload = envelope['payload']
            if (not isinstance(payload, dict) or set(payload) != {'schemaVersion', 'fingerprint', 'files'}
                    or payload['schemaVersion'] != 1 or payload['fingerprint'] != self.public_fingerprint
                    or not isinstance(payload['files'], dict)):
                raise ValueError('Invalid manifest payload.')
            self._private.public_key().verify(_decode(envelope['signature'], 64),
                                               MANIFEST_DOMAIN + _canonical(payload))
            if payload['files'] != self._files():
                return self._fail('A saved timing record was changed, added, or removed outside an authorized update. Timing export is blocked.')
            self._verified_transaction = True
            self.notice = ''
            return True
        except (OSError, ValueError, TypeError, InvalidSignature, RecursionError):
            return self._fail('The signed timing history could not be verified. Timing export is blocked.')

    def seal(self):
        """Commit an authorized transaction; never clear a failed verification.

        Application writes must be serialized by its tracker lock. This is not
        a filesystem transaction and does not claim to stop a hostile owner
        modifying files during that transaction.
        """
        if self.tainted or self._private is None:
            return False
        if not self._verified_transaction:
            return self._fail('Timing files were updated without a preceding integrity verification. Export is blocked.')
        self._verified_transaction = False
        try:
            if not self._controls_unchanged():
                return self._fail('Signing metadata changed during an update. Timing export is blocked.')
            self._write_manifest(self._files())
        except (OSError, ValueError, TypeError, RecursionError):
            return self._fail('Timing records could not be sealed safely. Timing export is blocked.')
        # The manifest commit is already durable. A temporarily locked cleanup
        # file must not turn authenticated records into permanently tainted ones.
        self._cleanup_recovery()
        self.notice = ''
        return True

    def _cleanup_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            if CLEANUP_NOTICE not in self.recovery_notice:
                self.recovery_notice = (self.recovery_notice + ' ' + CLEANUP_NOTICE).strip()
            return False
        self.recovery_notice = self.recovery_notice.replace(CLEANUP_NOTICE, '').strip()
        return True

    def begin_update(self):
        """Save the previous authenticated state before any authorized mutation.

        Recovery may discard unsealed writes, but can never adopt them as trusted.
        Immutable archives are checked by hash rather than copied every poll.
        """
        if not self.verify():
            return False
        try:
            manifest = self.manifest_path.read_bytes()
            current = self._files()
            snapshots = [name for name in TIMING_FILES if name in current]
            # Base64 alone cannot exceed the reader's limit. Check before
            # loading large histories, then include JSON/signature overhead below.
            encoded_size = 4 * ((len(manifest) + 2) // 3)
            encoded_size += sum(4 * (((self.directory/name).stat().st_size + 2) // 3)
                                for name in snapshots)
            if encoded_size > MAX_RECOVERY_BYTES:
                return self._fail('The recovery checkpoint exceeds the supported size. Recording is blocked before timing files are changed.')
            payload = dict(schemaVersion=1, fingerprint=self.public_fingerprint,
                manifest=_b64(manifest), files={name:_b64((self.directory/name).read_bytes())
                    for name in snapshots})
            envelope = dict(payload=payload, signature=_b64(self._private.sign(RECOVERY_DOMAIN+_canonical(payload))))
            serialized = _canonical(envelope)
            if len(serialized) > MAX_RECOVERY_BYTES:
                return self._fail('The recovery checkpoint exceeds the supported size. Recording is blocked before timing files are changed.')
            self._atomic(self.recovery_path, serialized)
            return True
        except (OSError, ValueError, TypeError):
            return self._fail('A recovery checkpoint could not be saved. Recording is blocked.')

    def _recover_checkpoint(self):
        """Recover only a signed before-image after an unexpected process exit."""
        envelope = self._read_json(self.recovery_path, MAX_RECOVERY_BYTES)
        if not isinstance(envelope, dict) or set(envelope) != {'payload','signature'}:
            raise ValueError('Invalid recovery checkpoint.')
        payload=envelope['payload']
        if (not isinstance(payload,dict) or set(payload)!={'schemaVersion','fingerprint','manifest','files'}
                or payload['schemaVersion']!=1 or payload['fingerprint']!=self.public_fingerprint
                or not isinstance(payload['files'],dict) or set(payload['files'])-set(TIMING_FILES)):
            raise ValueError('Invalid recovery checkpoint payload.')
        self._private.public_key().verify(_decode(envelope['signature'],64), RECOVERY_DOMAIN+_canonical(payload))
        manifest_bytes=_decode(payload['manifest'])
        manifest=json.loads(manifest_bytes)
        baseline=manifest['payload']
        self._private.public_key().verify(_decode(manifest['signature'],64), MANIFEST_DOMAIN+_canonical(baseline))
        if baseline.get('fingerprint')!=self.public_fingerprint or not isinstance(baseline.get('files'),dict):
            raise ValueError('Invalid recovery baseline.')
        snapshots={name:_decode(value) for name,value in payload['files'].items()}
        if set(snapshots)!=(set(baseline['files']) & set(TIMING_FILES)):
            raise ValueError('Recovery snapshot is incomplete.')
        for name,value in snapshots.items():
            if hashlib.sha256(value).hexdigest()!=baseline['files'][name]:raise ValueError('Recovery snapshot mismatch.')
        current=self._files()
        current_manifest=self._read_json(self.manifest_path)
        self._private.public_key().verify(_decode(current_manifest['signature'],64),
            MANIFEST_DOMAIN+_canonical(current_manifest['payload']))
        if current_manifest['payload'].get('files')==current:
            # The commit completed and only cleanup was interrupted.
            self._cleanup_recovery()
            return
        if self.manifest_path.read_bytes()!=manifest_bytes:
            raise ValueError('Recovery cannot replace an unexpected manifest.')
        for name,digest in baseline['files'].items():
            if name not in TIMING_FILES and current.get(name)!=digest:
                raise ValueError('A previously sealed archive changed; recovery is blocked.')
        affected=[name for name in set(current)|set(baseline['files']) if current.get(name)!=baseline['files'].get(name)]
        quarantine=self.directory/'recovery-uncommitted'/secrets.token_hex(12)
        for name in affected:
            source=self.directory/name
            if source.resolve().is_relative_to(self.directory.resolve()) is not True or source.is_symlink():
                raise ValueError('Invalid recovery path.')
            if source.exists():
                target=quarantine/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.move(str(source),str(target))
            if name in snapshots:self._atomic(source,snapshots[name])
        if self._files()!=baseline['files']:raise ValueError('Recovery did not restore the verified snapshot.')
        self.recovered=True
        self.recovery_notice='An interrupted write was recovered from the last signed checkpoint. Uncommitted data was preserved separately; missing observations were not invented.'
        self._cleanup_recovery()

    def sign_report(self, text):
        """Return visible TXT followed by a portable, pinned-key-verifiable footer."""
        if not isinstance(text, str):
            raise ValueError('The export report must contain text.')
        if '----- BEGIN TARNISHED LINEUP SIGNATURE -----' in text or '----- END TARNISHED LINEUP SIGNATURE -----' in text:
            raise ValueError('The report already contains a signature marker.')
        if not self.verify():
            raise ValueError(self.notice or 'Timing record integrity is unavailable.')
        payload = text if text.endswith('\n') else text + '\n'
        encoded = payload.encode('utf-8')
        footer = dict(schemaVersion=1, algorithm='Ed25519', publicKey=_b64(self._public),
                      fingerprint=self.public_fingerprint, payloadSha256=hashlib.sha256(encoded).hexdigest(),
                      signature=_b64(self._private.sign(REPORT_DOMAIN + encoded)))
        return payload + REPORT_BEGIN + _canonical(footer).decode('utf-8') + REPORT_END
