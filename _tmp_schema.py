import sqlite3, json
from pathlib import Path
con=sqlite3.connect(r'F:\YouTube_AI_Factory\_HE_THONG\data\youtube_monitor.db')
con.row_factory=sqlite3.Row
print([dict(r) for r in con.execute('pragma table_info(project_timeline_segments)').fetchall()])
