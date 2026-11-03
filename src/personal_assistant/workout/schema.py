"""Move legacy single-owner records into the owner partition without changing their IDs."""

OWNER = 'owner'

TABLES = {
    'entities': ('kind TEXT,id TEXT,revision INTEGER NOT NULL,deleted INTEGER NOT NULL,'
                 'data TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(user_id,kind,id)'),
    'changes': ('revision INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,id TEXT,'
                'deleted INTEGER,data TEXT,at REAL,actor TEXT'),
    'mutations': ('id TEXT,request TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,id)'),
    'imports': 'hash TEXT,report TEXT NOT NULL,raw TEXT NOT NULL,at REAL,original BLOB,PRIMARY KEY(user_id,hash)',
    'blobs': 'id TEXT,mime TEXT NOT NULL,body BLOB NOT NULL,at REAL,PRIMARY KEY(user_id,id)',
    'trainer': ('id TEXT,question TEXT NOT NULL,photos TEXT NOT NULL,context TEXT NOT NULL,created REAL,'
                'state TEXT NOT NULL,answer TEXT,proposals TEXT,token TEXT,lease_until REAL,'
                'approved INTEGER NOT NULL DEFAULT 0,answered_at REAL,PRIMARY KEY(user_id,id)'),
    'specialist': 'id INTEGER CHECK(id=1),seen REAL,state TEXT,detail TEXT,PRIMARY KEY(user_id,id)',
}


def initialize(db):
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('BEGIN IMMEDIATE')
    for table, columns in TABLES.items():
        legacy = [row['name'] for row in db.execute(f'PRAGMA table_info({table})')]
        if 'user_id' in legacy:
            continue
        if legacy:
            db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
        db.execute(f'CREATE TABLE {table}(user_id TEXT NOT NULL,{columns})')
        if legacy:
            column_list = ','.join(legacy)
            db.execute(f'INSERT INTO {table}(user_id,{column_list}) SELECT ?,{column_list} FROM legacy_{table}', (OWNER,))
            db.execute(f'DROP TABLE legacy_{table}')
    db.execute('CREATE INDEX IF NOT EXISTS workout_changes_user_revision ON changes(user_id,revision)')
    db.execute('CREATE INDEX IF NOT EXISTS workout_trainer_user_created ON trainer(user_id,created)')
    if 'timings' not in {row['name'] for row in db.execute('PRAGMA table_info(trainer)')}:
        # Phase timestamps (claimed, model started, first output, answered); never shown to athletes.
        db.execute('ALTER TABLE trainer ADD COLUMN timings TEXT')
    db.execute("""CREATE TABLE IF NOT EXISTS train_reminder_preferences(
        user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, roast INTEGER NOT NULL, photo_id TEXT,
        scheduled_sprints INTEGER NOT NULL DEFAULT 0, photos_enabled INTEGER NOT NULL DEFAULT 0,
        photo_ids TEXT NOT NULL DEFAULT '[]')""")
    preferences = {row['name'] for row in db.execute('PRAGMA table_info(train_reminder_preferences)')}
    if 'scheduled_sprints' not in preferences:
        db.execute('ALTER TABLE train_reminder_preferences ADD COLUMN scheduled_sprints INTEGER NOT NULL DEFAULT 0')
    if 'photos_enabled' not in preferences:
        db.execute('ALTER TABLE train_reminder_preferences ADD COLUMN photos_enabled INTEGER NOT NULL DEFAULT 0')
    if 'photo_ids' not in preferences:
        db.execute("ALTER TABLE train_reminder_preferences ADD COLUMN photo_ids TEXT NOT NULL DEFAULT '[]'")
        db.execute('UPDATE train_reminder_preferences SET photo_ids=json_array(photo_id) WHERE photo_id IS NOT NULL')
