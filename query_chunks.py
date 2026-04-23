import sys
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3
conn = sqlite3.connect('kg2m.db')
cursor = conn.cursor()
cursor.execute("SELECT chunk_index, title, length(summary), length(content) FROM document_chunks WHERE document_id='doc-52036cdb1906' ORDER BY chunk_index;")
rows = cursor.fetchall()
print('| Thứ tự Chunk | Tiêu đề | Ký tự tóm tắt | Ký tự nội dung |')
print('|:---:|:---|:---:|:---:|')
for r in rows:
    summary_len = r[2] if r[2] else 0
    content_len = r[3] if r[3] else 0
    print(f'| {r[0]} | {r[1]} | {summary_len} | {content_len} |')
