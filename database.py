import os
import io
import json
import builtins
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def init_database():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS json_store (
                    filename TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS uploaded_files (
                    filename TEXT PRIMARY KEY,
                    content BYTEA NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_uploaded_files_created_at
                ON uploaded_files(created_at)
            """)
        conn.commit()
    finally:
        conn.close()


def json_exists(filename):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM json_store WHERE filename=%s LIMIT 1", (filename,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def json_load(filename):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM json_store WHERE filename=%s", (filename,))
            row = cur.fetchone()
            if not row:
                raise FileNotFoundError(filename)
            return row["data"]
    finally:
        conn.close()


def json_save(filename, data):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO json_store(filename, data)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (filename)
                DO UPDATE SET data=EXCLUDED.data
            """, (filename, json.dumps(data, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def json_delete(filename):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM json_store WHERE filename=%s", (filename,))
        conn.commit()
    finally:
        conn.close()


class _DatabaseJSONFile(io.StringIO):
    def __init__(self, filename, mode):
        self._filename = filename
        self._mode = mode
        if "r" in mode:
            data = json_load(filename)
            text = json.dumps(data, ensure_ascii=False)
        else:
            text = ""
        super().__init__(text)

    def close(self):
        if not self.closed and ("w" in self._mode or "a" in self._mode or "x" in self._mode):
            self.seek(0)
            text = self.read()
            try:
                data = json.loads(text) if text.strip() else None
                if data is None:
                    data = []
                json_save(self._filename, data)
            except Exception:
                # Never hide the original application error during close.
                raise
        super().close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.close()
        else:
            super().close()
        return False


_ORIGINAL_OPEN = builtins.open
_ORIGINAL_EXISTS = os.path.exists


def install_json_compatibility():
    """Make the existing JSON-based routes transparently use PostgreSQL."""
    def db_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and str(file).lower().endswith(".json"):
            filename = os.path.basename(os.fspath(file))
            if "r" in mode and not json_exists(filename):
                raise FileNotFoundError(filename)
            if "x" in mode and json_exists(filename):
                raise FileExistsError(filename)
            return _DatabaseJSONFile(filename, mode)
        return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

    def db_exists(path):
        if isinstance(path, (str, os.PathLike)) and str(path).lower().endswith(".json"):
            return json_exists(os.path.basename(os.fspath(path)))
        return _ORIGINAL_EXISTS(path)

    builtins.open = db_open
    os.path.exists = db_exists


def save_uploaded_file(file_storage, filename):
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise ValueError("No file supplied")
    content = file_storage.read()
    content_type = getattr(file_storage, "mimetype", None) or "application/octet-stream"

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO uploaded_files(filename, content, content_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (filename)
                DO UPDATE SET content=EXCLUDED.content,
                              content_type=EXCLUDED.content_type
            """, (filename, psycopg2.Binary(content), content_type))
        conn.commit()
    finally:
        conn.close()


def get_uploaded_file(filename):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, content_type FROM uploaded_files WHERE filename=%s",
                (filename,)
            )
            row = cur.fetchone()
            return row
    finally:
        conn.close()


def delete_uploaded_file(filename):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM uploaded_files WHERE filename=%s", (filename,))
        conn.commit()
    finally:
        conn.close()


# Initialize once when the Flask process starts, then redirect JSON access to PostgreSQL.
init_database()
install_json_compatibility()
