import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class GameTests(unittest.TestCase):
    def setUp(self):
        app.ROOMS.clear()
        room_created = app.new_room()
        self.code = room_created['code']
        self.host_token = room_created['hostToken']
        self.host_player = room_created['participantToken']
        self.room = app.ROOMS[self.code]

    def join(self, name):
        status, payload = app.join_room(self.room, {'name': name})
        self.assertEqual(status, 200)
        return payload['participantToken']

    def test_complete_game_and_anonymity(self):
        a = self.join('たなか')
        b = self.join('さとう')
        status, _ = app.update_room(self.room, 'start', {'hostToken': self.host_token})
        self.assertEqual(status, 200)
        self.assertEqual(self.room['status'], 'voting')
        self.assertEqual(app.get_state(self.room, self.host_token)['votedCount'], 0)
        status, _ = app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': b})
        self.assertEqual(status, 200)
        status, _ = app.update_room(self.room, 'vote', {'participantToken': b, 'candidateId': a})
        self.assertEqual(status, 200)
        host_state = app.get_state(self.room, self.host_token)
        self.assertNotIn('results', host_state)
        self.assertIsNone(host_state['myVote'])
        self.assertEqual(host_state['votedCount'], 2)
        state_a = app.get_state(self.room, a)
        self.assertEqual(state_a['myVote'], b)
        self.assertNotIn('results', state_a)
        self.assertEqual(app.update_room(self.room, 'reveal', {'hostToken': self.host_token})[0], 200)
        results = app.get_state(self.room, a)['results']
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]['rank'], 1)
        self.assertEqual(results[1]['rank'], 1)
        self.assertEqual(self.room['round'], 1)
        self.assertEqual(app.update_room(self.room, 'next', {'hostToken': self.host_token})[0], 200)
        self.assertEqual(self.room['round'], 2)
        self.assertEqual(app.get_state(self.room, a)['topic']['question'], 'この中で一番面白いのは誰？？')
        self.assertEqual(app.get_state(self.room, a)['myVote'], None)

    def test_reject_illegal_actions(self):
        a = self.join('あ')
        b = self.join('い')
        self.assertEqual(app.join_room(self.room, {'name': 'あ'})[0], 400)
        self.assertEqual(app.update_room(self.room, 'start', {'hostToken': 'wrong'})[0], 403)
        self.assertEqual(app.update_room(self.room, 'start', {'hostToken': self.host_token})[0], 200)
        self.assertEqual(app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': a})[0], 400)
        self.assertEqual(app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': 'bogus'})[0], 400)
        self.assertEqual(app.update_room(self.room, 'reveal', {'hostToken': self.host_token})[0], 400)
        self.assertEqual(app.update_room(self.room, 'next', {'hostToken': self.host_token})[0], 400)
        self.assertEqual(app.update_room(self.room, 'vote', {'participantToken': b, 'candidateId': a})[0], 200)
        self.assertEqual(app.update_room(self.room, 'reveal', {'hostToken': self.host_token})[0], 200)
        self.assertEqual(app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': b})[0], 400)

    def test_late_join_next_round(self):
        a = self.join('あ')
        b = self.join('い')
        app.update_room(self.room, 'start', {'hostToken': self.host_token})
        c = self.join('う')
        self.assertFalse(app.get_state(self.room, c)['eligible'])
        self.assertEqual(app.update_room(self.room, 'vote', {'participantToken': c, 'candidateId': a})[0], 400)
        app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': b})
        app.update_room(self.room, 'reveal', {'hostToken': self.host_token})
        app.update_room(self.room, 'next', {'hostToken': self.host_token})
        self.assertTrue(app.get_state(self.room, c)['eligible'])
        self.assertEqual(app.get_state(self.room, c)['voterCount'], 4)

    def test_rename_and_validation(self):
        a = self.join('山田')
        self.assertEqual(app.join_room(self.room, {'name': '山田', 'participantToken': a})[0], 200)
        self.assertEqual(len(self.room['participants']), 2)
        self.assertEqual(app.join_room(self.room, {'name': 'a' * 15})[0], 400)
        self.assertEqual(app.join_room(self.room, {'name': '<img src=x onerror=1>'})[0], 400)

    def test_only_fixed_question_and_host_participates(self):
        host = app.get_state(self.room, self.host_token)
        self.assertEqual(host['me']['name'], '橋野')
        self.assertNotEqual(self.host_token, self.host_player)
        self.assertNotIn(self.host_token, str(host['participants']))
        self.assertEqual(app.update_room(self.room, 'start', {'hostToken': self.host_token})[0], 400)
        a = self.join('参加者')
        self.assertEqual(app.join_room(self.room, {'name': '橋野'})[0], 400)
        self.assertEqual(app.update_room(self.room, 'add-topic', {
            'hostToken': self.host_token, 'question': '別の質問'})[0], 400)
        app.update_room(self.room, 'start', {'hostToken': self.host_token})
        for _ in range(3):
            state = app.get_state(self.room, self.host_token)
            self.assertEqual(state['topic']['question'], 'この中で一番面白いのは誰？？')
            self.assertTrue(state['eligible'])
            self.assertNotIn('hostWinner', state)
            app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': self.host_player})
            app.update_room(self.room, 'vote', {'participantToken': self.host_player, 'candidateId': a})
            self.assertEqual(app.get_state(self.room, self.host_token)['myVote'], a)
            app.update_room(self.room, 'reveal', {'hostToken': self.host_token})
            self.assertTrue(app.get_state(self.room, a)['hostWinner'])  # Tied first also wins.
            app.update_room(self.room, 'next', {'hostToken': self.host_token})

    def test_host_win_and_loss(self):
        a = self.join('A')
        b = self.join('B')
        app.update_room(self.room, 'start', {'hostToken': self.host_token})
        for token in [a, b]:
            app.update_room(self.room, 'vote', {'participantToken': token, 'candidateId': self.host_player})
        app.update_room(self.room, 'reveal', {'hostToken': self.host_token})
        self.assertTrue(app.get_state(self.room, a)['hostWinner'])
        app.update_room(self.room, 'next', {'hostToken': self.host_token})
        for token in [self.host_player, b]:
            app.update_room(self.room, 'vote', {'participantToken': token, 'candidateId': a})
        app.update_room(self.room, 'reveal', {'hostToken': self.host_token})
        self.assertFalse(app.get_state(self.room, b)['hostWinner'])


if __name__ == '__main__':
    unittest.main()
