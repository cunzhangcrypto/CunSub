import sqlite3
from app.config import DB_PATH


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'uploaded',
        source_file_path TEXT,
        source_file_type TEXT,
        source_duration REAL DEFAULT 0,
        source_size INTEGER DEFAULT 0,
        audio_path TEXT,
        gemini_file_uri TEXT,
        gemini_file_name TEXT,
        offset_ms INTEGER DEFAULT 200,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS understandings (
        project_id TEXT PRIMARY KEY,
        content_summary TEXT,
        key_points TEXT,
        technical_terms TEXT,
        suspected_errors TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS confirmations (
        project_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'pending',
        terms_mapping TEXT,
        additional_terms TEXT,
        term_corrections TEXT,
        confirmed_at TEXT,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS subtitles (
        project_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        text TEXT NOT NULL,
        edited INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, idx),
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS exports (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        format TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS term_library (
        term TEXT PRIMARY KEY,
        aliases TEXT,
        source_project_id TEXT,
        confirmed_count INTEGER DEFAULT 1,
        domain TEXT
    );

    CREATE TABLE IF NOT EXISTS progress (
        project_id TEXT PRIMARY KEY,
        step TEXT,
        percent INTEGER DEFAULT 0,
        message TEXT,
        updated_at TEXT
    );
    """)
    conn.commit()

    # 迁移：为旧数据库的 confirmations 表补 term_corrections 列
    try:
        conn.execute("ALTER TABLE confirmations ADD COLUMN term_corrections TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移：为旧数据库的 projects 表补 offset_ms 列(字幕整体偏移,默认200ms补偿Gemini时间戳偏早)
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN offset_ms INTEGER DEFAULT 200")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 列已存在

    conn.close()
