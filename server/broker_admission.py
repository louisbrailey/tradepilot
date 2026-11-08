"""Cross-application single-writer admission. Never expire uncertain holds."""
import os
from private_storage import ensure_private_directory
from contextlib import contextmanager
import sqlite3
import uuid
from pathlib import Path

DEFAULT_PATH = (Path(r'C:/ProgramData/TradePilot/private/runtime/admission.sqlite3') if os.name == 'nt'
                else Path.home() / 'Library/Application Support/BrokerAccess/admission.sqlite3')


class AdmissionError(Exception):
    pass


class AdmissionLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else (Path(os.environ["TRADEPILOT_RUNTIME"]) / "admission.sqlite3" if os.name == "nt" and "TRADEPILOT_RUNTIME" in os.environ else DEFAULT_PATH)
        ensure_private_directory(self.path.parent)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS broker_admission (
                provider TEXT, environment TEXT, account_id TEXT, action_id TEXT,
                owner TEXT, state TEXT, PRIMARY KEY(provider,environment,account_id))''')
        if os.name == "nt":
            from windows_runtime import private_path
            private_path(self.path)
        else:
            os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, provider, environment, accounts, action_id):
        if provider == 'coinbase':
            accounts = [str(uuid.UUID(account)) for account in accounts]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for account in sorted(set(accounts)):
                row = db.execute('SELECT action_id,owner,state FROM broker_admission WHERE provider=? AND environment=? AND account_id=?',
                                 (provider, environment, account)).fetchone()
                if row:
                    raise AdmissionError('An unresolved broker action holds this account; authoritative resolution is required.')
            for account in sorted(set(accounts)):
                db.execute('INSERT INTO broker_admission VALUES (?,?,?,?,?,?)',
                           (provider, environment, account, action_id, 'tradepilot', 'RESERVED'))

    def require_owned(self, provider, environment, account, action_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT action_id,owner,state FROM broker_admission WHERE provider=? AND environment=? AND account_id=?',
                             (provider, environment, account)).fetchone()
            if row != (action_id, 'tradepilot', 'SUBMITTING'):
                raise AdmissionError('The existing order does not have an eligible owned hold.')

    def transition(self, action_id, state):
        if state not in ('SUBMITTING', 'UNKNOWN'):
            raise AdmissionError('Invalid admission state')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute('UPDATE broker_admission SET state=? WHERE action_id=? AND owner=?',
                                (state, action_id, 'tradepilot'))
            if not result.rowcount:
                raise AdmissionError('Missing admission hold')

    def release(self, action_id):
        # Caller must have authoritative rejection/terminal evidence, or know no send occurred.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM broker_admission WHERE action_id=? AND owner=?', (action_id, 'tradepilot'))
