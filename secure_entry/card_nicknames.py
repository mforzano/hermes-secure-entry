"""Profile-local display metadata; the native vault alone grants card scope."""
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from stat import S_ISREG

from .native import add_card, is_reusable_card

MAX_NICKNAME = 32


def clean_nickname(value):
    # Reject numeric payment data, markup, Unicode formatting and controls rather
    # than escaping or attempting to redact an arbitrary user-supplied string.
    if (not isinstance(value, str) or len(value) > MAX_NICKNAME
            or not re.fullmatch(r'[A-Za-z]+(?: [A-Za-z]+)*', value)):
        raise ValueError('invalid_nickname')
    return value


class CardNicknames:
    def __init__(self, home):
        self.path = Path(home) / 'secure-entry-card-nicknames.sqlite3'

    def _uri(self, mode):
        return self.path.absolute().as_uri() + '?mode=' + mode

    def _exists(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return False
        if not S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError('invalid_nickname_store')
        return True

    def snapshot(self):
        # No database/directory is created by list or fill.
        if not self._exists():
            return {}
        with closing(sqlite3.connect(self._uri('ro'), uri=True)) as db:
            # A reader may arrive between a writer creating the file and its
            # first commit. This is still an empty committed snapshot.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nicknames'").fetchone():
                return {}
            return {handle: clean_nickname(label) for handle, label in
                    db.execute('SELECT handle, nickname FROM nicknames')}

    @contextmanager
    def _write(self):
        self._exists()
        with closing(sqlite3.connect(self._uri('rwc'), uri=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS nicknames '
                       '(handle TEXT PRIMARY KEY NOT NULL, nickname TEXT NOT NULL COLLATE NOCASE UNIQUE)')
            yield db

    @staticmethod
    def _conflict(db, store, handle, nickname):
        row = db.execute('SELECT handle FROM nicknames WHERE nickname = ?', (nickname,)).fetchone()
        if row is None or row[0] == handle:
            return False
        if is_reusable_card(store.get_meta(row[0])):
            return True
        db.execute('DELETE FROM nicknames WHERE handle = ?', (row[0],))
        return False

    def rename(self, store, handle, expected, nickname):
        nickname = clean_nickname(nickname)
        with self._write() as db:
            if not is_reusable_card(store.get_meta(handle)):
                db.execute('DELETE FROM nicknames WHERE handle = ?', (handle,))
                return 'card_unavailable'
            row = db.execute('SELECT nickname FROM nicknames WHERE handle = ?', (handle,)).fetchone()
            if (row[0] if row else None) != expected:
                return 'nickname_changed'
            if self._conflict(db, store, handle, nickname):
                return 'nickname_taken'
            db.execute('INSERT INTO nicknames VALUES (?, ?) '
                       'ON CONFLICT(handle) DO UPDATE SET nickname = excluded.nickname', (handle, nickname))
        return 'renamed' if is_reusable_card(store.get_meta(handle)) else 'card_unavailable'

    def forget(self, handle):
        if self._exists():
            with self._write() as db:
                db.execute('DELETE FROM nicknames WHERE handle = ?', (handle,))

    def save(self, store, fields):
        # Keep the nickname out of the payment payload, even on failure.
        fields = dict(fields)
        nickname = fields.pop('nickname', None)
        if nickname is None:
            return add_card(store, None, fields, reusable=True)
        nickname = clean_nickname(nickname)
        result = None
        try:
            with self._write() as db:
                if self._conflict(db, store, None, nickname):
                    return {'status': 'nickname_taken'}
                result = add_card(store, None, fields, reusable=True)
                if result['status'] == 'saved':
                    db.execute('INSERT INTO nicknames VALUES (?, ?)', (result['handle'], nickname))
        except (OSError, sqlite3.Error):
            if result is None:
                return {'status': 'nickname_unavailable'}
            if result['status'] == 'saved':
                # The native save is independent of the display transaction.
                # Do not retry it or falsely report that nothing was saved.
                return {**result, 'nickname_status': 'unverified'}
        return result
