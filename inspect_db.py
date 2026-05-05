import sqlite3
con = sqlite3.connect('data/world.db', timeout=10)
print('assembly docs    :', con.execute("SELECT COUNT(*) FROM documents WHERE source='assembly'").fetchone()[0])
print('with SUMMARY     :', con.execute("SELECT COUNT(*) FROM documents WHERE source='assembly' AND json_extract(metadata_json, '$.summary_fetched_at') IS NOT NULL").fetchone()[0])
print('latest fetch_at  :', con.execute("SELECT MAX(fetched_at) FROM documents WHERE source='assembly'").fetchone()[0])
print('all docs         :', con.execute('SELECT COUNT(*) FROM documents').fetchone()[0])