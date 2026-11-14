"""Dependency-free checks for new v13 source and SQL migrations."""
import ast, pathlib, sqlite3, re
base=pathlib.Path(__file__).parent
s=(base/'main.py').read_text()
tree=ast.parse(s)
functions={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
classes={n.name for n in ast.walk(tree) if isinstance(n,ast.ClassDef)}
assert {'enemy_intent','boss_phase','encounter_kind','resolve_encounter','elite_action','raid_attack','raid_claim','merchant_menu','purchase_merchant','open_encounter'}.issubset(functions)
assert {'EncounterView','EliteView','RaidView','MerchantView','PlayMenu'}.issubset(classes)
assert "if _cmd.name!='play': bot.tree.remove_command(_cmd.name)" in s
# Exercise the actual v13 SQL DDL in an in-memory SQLite database.
start=s.index("conn.executescript('''\nCREATE TABLE IF NOT EXISTS dungeon_encounters")
end=s.index("''')",start)
sql=s[start+len("conn.executescript('''"):end]
c=sqlite3.connect(':memory:');c.executescript(sql)
for table in ['dungeon_encounters','elite_trials','merchant_purchases','world_raids','raid_participation']:
    assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
c.execute("INSERT INTO dungeon_encounters(user_id,floor,kind) VALUES(?,?,?)",(1,10,'doors'))
c.execute("UPDATE dungeon_encounters SET status='claimed' WHERE user_id=1 AND floor=10 AND status='pending'")
assert c.execute("UPDATE dungeon_encounters SET status='claimed' WHERE user_id=1 AND floor=10 AND status='pending'").rowcount==0
try:
    c.execute("INSERT INTO dungeon_encounters(user_id,floor,kind) VALUES(?,?,?)",(1,10,'doors'))
    raise AssertionError('duplicate encounter claim permitted')
except sqlite3.IntegrityError:pass
c.close()
for f in ['arena.py','visuals.py']:
    ast.parse((base/f).read_text())
print('PASS: AST, player menu, v13 handlers, additive SQLite schema and duplicate claim protection')
