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
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['rank'], 1)
        self.assertEqual(results[1]['rank'], 1)
        self.assertEqual(self.room['round'], 1)
        self.assertEqual(app.update_room(self.room, 'next', {'hostToken': self.host_token})[0], 200)
        self.assertEqual(self.room['round'], 2)
        self.assertNotEqual(self.room['topic_index'], self.room['used_topics'][0])
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
        self.assertEqual(app.get_state(self.room, c)['voterCount'], 3)

    def test_rename_and_validation(self):
        a = self.join('山田')
        self.assertEqual(app.join_room(self.room, {'name': '山田', 'participantToken': a})[0], 200)
        self.assertEqual(len(self.room['participants']), 1)
        self.assertEqual(app.join_room(self.room, {'name': 'a' * 15})[0], 400)
        self.assertEqual(app.join_room(self.room, {'name': '<img src=x onerror=1>'})[0], 400)

    def test_host_adds_questions_to_existing_topic_pool(self):
        question = 'この中でいちばん動物と話せそうなのは？'
        self.assertEqual(app.update_room(self.room, 'add-topic', {
            'hostToken': self.host_token, 'question': question})[0], 200)
        self.assertEqual(len(app.TOPICS), 30)
        self.assertEqual(self.room['custom_topics'], [(question, app.CUSTOM_AWARD)])
        self.assertEqual(app.get_state(self.room, self.host_token)['customQuestions'], [question])
        a = self.join('田中')
        self.join('佐藤')
        self.assertNotIn('customQuestions', app.get_state(self.room, a))
        self.assertEqual(app.update_room(self.room, 'start', {'hostToken': self.host_token})[0], 200)
        # Every one of the 31 questions appears exactly once before any repeats.
        questions = []
        for i in range(31):
            if i:
                self.room['status'] = 'revealed'
                self.assertEqual(app.update_room(self.room, 'next', {'hostToken': self.host_token})[0], 200)
            questions.append(app.get_state(self.room, self.host_token)['topic']['question'])
        self.assertEqual(len(set(questions)), 31)
        self.assertIn(question, questions)
        self.assertEqual(len(self.room['used_topics']), 31)

    def test_add_question_authorization_and_validation(self):
        self.assertEqual(app.update_room(self.room, 'add-topic', {'question': '無断追加'})[0], 403)
        self.assertEqual(app.update_room(self.room, 'add-topic', {
            'hostToken': 'not-host', 'question': '無断追加'})[0], 403)
        for invalid in ['', '  \n  ', 'a' * 121, 123, 'foo\x00bar']:
            self.assertEqual(app.update_room(self.room, 'add-topic', {
                'hostToken': self.host_token, 'question': invalid})[0], 400)
        question = 'オリジナルのお題は誰？'
        payload = {'hostToken': self.host_token, 'question': question}
        self.assertEqual(app.update_room(self.room, 'add-topic', payload)[0], 200)
        self.assertEqual(app.update_room(self.room, 'add-topic', payload)[0], 400)
        self.assertEqual(app.update_room(self.room, 'add-topic', {
            'hostToken': self.host_token, 'question': app.TOPICS[0][0]})[0], 400)
        self.assertEqual(len(self.room['custom_topics']), 1)

    def test_added_questions_during_voting_applies_next_round(self):
        a = self.join('あ')
        b = self.join('い')
        app.update_room(self.room, 'start', {'hostToken': self.host_token})
        current = app.get_state(self.room, self.host_token)['topic']['question']
        question = '今追加されたお題は誰？'
        self.assertEqual(app.update_room(self.room, 'add-topic', {
            'hostToken': self.host_token, 'question': question})[0], 200)
        self.assertEqual(app.get_state(self.room, self.host_token)['topic']['question'], current)
        app.update_room(self.room, 'vote', {'participantToken': a, 'candidateId': b})
        app.update_room(self.room, 'reveal', {'hostToken': self.host_token})
        # Make every existing topic count as used, so the newly-added one is next.
        self.room['used_topics'] = list(range(30))
        app.update_room(self.room, 'next', {'hostToken': self.host_token})
        state = app.get_state(self.room, self.host_token)
        self.assertEqual(state['topic'], {'question': question, 'award': app.CUSTOM_AWARD})


if __name__ == '__main__':
    unittest.main()
