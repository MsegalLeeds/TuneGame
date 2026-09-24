import pytest

from SongGame import MIN_MULTIPLIER, POINTS_PER_QUESTION, STREAK_BONUS, SongGame


@pytest.fixture
def game():
    # Bypass CSV/Spotify setup: scoring only needs score and streak.
    game = SongGame.__new__(SongGame)
    game.score = 0
    game.streak = 0
    game.questions_asked = 0
    return game


class TestAwardPoints:
    def test_correct_answer_awards_base_points(self, game):
        game.award_points(True)
        assert game.score == POINTS_PER_QUESTION
        assert game.streak == 1

    def test_wrong_answer_awards_no_points(self, game):
        game.award_points(False)
        assert game.score == 0
        assert game.streak == 0

    def test_wrong_answer_does_not_reduce_existing_score(self, game):
        game.score = 25
        game.streak = 2
        game.award_points(False)
        assert game.score == 25
        assert game.streak == 0

    def test_consecutive_correct_answers_add_streak_bonus(self, game):
        game.award_points(True)
        game.award_points(True)
        game.award_points(True)

        expected = (
            POINTS_PER_QUESTION
            + (POINTS_PER_QUESTION + STREAK_BONUS)
            + (POINTS_PER_QUESTION + 2 * STREAK_BONUS)
        )
        assert game.score == expected
        assert game.streak == 3

    def test_wrong_answer_resets_streak(self, game):
        game.award_points(True)
        game.award_points(True)
        assert game.streak == 2

        game.award_points(False)
        assert game.streak == 0

    def test_correct_after_wrong_starts_streak_again(self, game):
        game.award_points(True)
        game.award_points(False)
        game.award_points(True)

        assert game.streak == 1
        assert game.score == POINTS_PER_QUESTION * 2

    def test_fast_correct_answer_gets_full_base_points(self, game):
        game.award_points(True, time_taken=0, time_limit=30)
        assert game.score == POINTS_PER_QUESTION

    def test_slow_correct_answer_keeps_minimum_multiplier(self, game):
        game.award_points(True, time_taken=30, time_limit=30)
        expected = round(POINTS_PER_QUESTION * MIN_MULTIPLIER)
        assert game.score == expected
        assert game.streak == 1

    def test_timeout_does_not_award_points(self, game):
        # The API converts a timeout into correct=False before calling award_points.
        game.award_points(False, time_taken=30.1, time_limit=30)
        assert game.score == 0
        assert game.streak == 0

    @pytest.mark.parametrize("time_taken", [-10, 0, 1, 15, 30, 60, 1000])
    def test_time_based_score_never_becomes_negative(self, game, time_taken):
        game.award_points(True, time_taken=time_taken, time_limit=30)
        assert game.score >= round(POINTS_PER_QUESTION * MIN_MULTIPLIER)
