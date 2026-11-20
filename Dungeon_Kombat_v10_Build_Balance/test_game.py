import os, tempfile, unittest
from unittest.mock import patch
import game

class GameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=game.DB_PATH
        game.DB_PATH=os.path.join(self.tmp.name,'test.db')
    def tearDown(self):
        game.DB_PATH=self.old
        self.tmp.cleanup()
    def test_registration_and_time_cap(self):
        with game.open_db() as db:
            s=game.create_player(db,1,'Tester','Guardian',1000000)
            self.assertEqual(s['floor'],1)
            with self.assertRaises(ValueError):game.create_player(db,1,'Tester','Rogue',1000001)
            s,msg=game.refresh(db,1,'Tester',1000000+3600)
            self.assertGreater(s['wins']+s['fails']+s['farm'],0)
            self.assertLessEqual(s['wins']+s['fails']+s['farm'],240)
    def test_event_expiry(self):
        with game.open_db() as db:
            game.create_player(db,1,'Tester','Rogue',1000000)
            s,_=game.refresh(db,1,'Tester',1000000+8*86400)
            prev=s['floor']
            s,_=game.refresh(db,1,'Tester',1000000+9*86400)
            self.assertEqual(prev,s['floor'])
            with self.assertRaises(ValueError):game.mutate(db,1,'Tester','daily',1000000+9*86400)
    def test_leaderboard_and_smith(self):
        with game.open_db() as db:
            game.create_player(db,1,'A','Berserker',1000000)
            game.create_player(db,2,'B','Rogue',1000000)
            self.assertEqual(len(game.leaderboard(db)),2)
            s=game.get_player(db,1)
            s['materials']=100
            game.save_player(db,1,'A',s)
            s,msg=game.mutate(db,1,'A','upgrade_weapon',1000000)
            self.assertEqual(s['weapon']['plus'],1)
    def test_boss_gate(self):
        with game.open_db() as db:
            game.create_player(db,1,'A','Berserker',1000000)
            s=game.get_player(db,1);s['floor']=49;s['last_tick']=1000000
            game.save_player(db,1,'A',s)
            s,msg=game.refresh(db,1,'A',1000015)
            self.assertIsNotNone(s['boss'])
            self.assertEqual(s['floor'],49)

if __name__=='__main__':unittest.main()
