import sqlite3, json
con=sqlite3.connect(r'F:\YouTube_AI_Factory\_HE_THONG\data\youtube_monitor.db')
con.row_factory=sqlite3.Row
rows=con.execute('''select id, segment_index, duration_seconds, visual_path, audio_path, visual_kind, edit_transition, edit_effect, edit_note, edit_cleanups, overlays, sound_cues, required_assets, edit_direction from project_timeline_segments where project_id=? order by segment_index''',(56,)).fetchall()
print('timeline rows', len(rows))
for r in rows:
    d=dict(r)
    for k in ['edit_cleanups','overlays','sound_cues','required_assets','edit_direction']:
        try: d[k]=json.loads(d[k] or '[]')
        except Exception: pass
    print(json.dumps(d, ensure_ascii=False)[:2500])
plans=con.execute('select id,status,created_at,updated_at,plan_json from project_edit_plans where project_id=? order by updated_at desc limit 3',(56,)).fetchall()
print('plans', len(plans))
for r in plans:
    d=dict(r)
    try: d['plan_json']=json.loads(d['plan_json'] or '{}')
    except Exception: pass
    print(json.dumps(d, ensure_ascii=False)[:3000])
