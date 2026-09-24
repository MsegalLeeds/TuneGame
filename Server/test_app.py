import pytest

import app


class FakeGame:
    """Small deterministic game double for API tests."""

    def __init__(self):
        self.score = 0
        self.streak = 0
        self.questions_asked = 0
        self.row = None
        self._fields = {
            "Song": "Bohemian Rhapsody",
            "Album": "A Night at the Opera",
            "Artist": "Queen",
        }

    def sample_row(self):
        return object()

    def get_field(self, key):
        return self._fields[key]

    def format_questions(self, known, template):
        return template.replace("$", known)

    def generate_choices(self, correct, field):
        return ["Nevermind", "Thriller", correct, "Back in Black"]

    def is_close_match(self, guess, answer):
        return guess.strip().lower() == answer.strip().lower()

    def award_points(self, correct, time_taken=None, time_limit=None):
        if correct:
            self.streak += 1
            self.score += 10
        else:
            self.streak = 0


@pytest.fixture
def client(monkeypatch):
    game = FakeGame()
    monkeypatch.setattr(app, "SongGame", lambda: game)
    monkeypatch.setattr(app, "get_album_art", lambda song, artist: "https://example.com/art.jpg")
    app.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.app.test_client() as client:
        yield client, game


@pytest.fixture
def started_game(client):
    test_client, game = client
    response = test_client.post("/new-game")
    assert response.status_code == 200
    return test_client, game


class TestNewGame:
    def test_new_game_initialises_session_state(self, client):
        test_client, _ = client
        response = test_client.post("/new-game")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["lives"] == app.MAX_LIVES
        assert data["time_limit"] == app.TIME_LIMIT

        with test_client.session_transaction() as session:
            assert session["lives"] == app.MAX_LIVES
            assert session["score"] == 0
            assert session["streak"] == 0
            assert session["questions_asked"] == 0

    def test_new_game_clears_previous_question_state(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        with test_client.session_transaction() as session:
            assert "current_correct" in session

        test_client.post("/new-game")
        with test_client.session_transaction() as session:
            assert "current_correct" not in session
            assert "question_time" not in session
            assert "current_song" not in session
            assert "current_artist" not in session


class TestQuestion:
    def test_question_requires_active_game(self, client):
        test_client, _ = client
        with test_client.session_transaction() as session:
            session["lives"] = 0
        response = test_client.get("/question")
        assert response.status_code == 400
        assert "Game over" in response.get_json()["error"]

    def test_question_returns_expected_fields(self, started_game):
        test_client, _ = started_game
        response = test_client.get("/question")
        assert response.status_code == 200
        data = response.get_json()
        assert data["question"] == "Name the album that Bohemian Rhapsody is on? "
        assert data["mode"] == "mc"
        assert len(data["choices"]) == 4
        assert data["lives"] == app.MAX_LIVES
        assert data["time_limit"] == app.TIME_LIMIT
        assert data["album_art"] == "https://example.com/art.jpg"

    def test_question_stores_correct_answer_in_session(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        with test_client.session_transaction() as session:
            assert session["current_correct"] == "A Night at the Opera"
            assert session["current_song"] == "Bohemian Rhapsody"
            assert session["current_artist"] == "Queen"
            assert "question_time" in session
            assert session["correct_index"] in range(4)

    def test_question_does_not_work_after_game_over(self, started_game):
        test_client, _ = started_game
        with test_client.session_transaction() as session:
            session["lives"] = 0
        response = test_client.get("/question")
        assert response.status_code == 400
        assert "Game over" in response.get_json()["error"]


class TestAnswer:
    def test_answer_correct(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.status_code == 200
        data = response.get_json()
        assert data["correct"] is True
        assert data["correct_answer"] == "A Night at the Opera"
        assert data["timed_out"] is False
        assert data["lives"] == app.MAX_LIVES
        assert data["streak"] == 1
        assert data["score"] == 10

    def test_answer_wrong_decrements_life(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "Thriller"})
        assert response.status_code == 200
        data = response.get_json()
        assert data["correct"] is False
        assert data["correct_answer"] == "A Night at the Opera"
        assert data["lives"] == app.MAX_LIVES - 1
        assert data["streak"] == 0

    def test_answer_removes_current_question_from_session(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        test_client.post("/answer", json={"guess": "A Night at the Opera"})
        with test_client.session_transaction() as session:
            assert "current_correct" not in session
            assert "question_time" not in session

    def test_answer_without_question_is_rejected(self, started_game):
        test_client, _ = started_game
        response = test_client.post("/answer", json={"guess": "Queen"})
        assert response.status_code == 400
        assert "No active question" in response.get_json()["error"]

    def test_answer_without_json_is_rejected(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        response = test_client.post("/answer")
        assert response.status_code == 400
        assert response.get_json()["error"] == "No data provided"

    def test_answer_after_game_over_is_rejected(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        with test_client.session_transaction() as session:
            session["lives"] = 0
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.status_code == 400
        assert "Game over" in response.get_json()["error"]


class TestTimeout:
    def test_answer_times_out_after_time_limit(self, started_game, monkeypatch):
        test_client, _ = started_game
        monkeypatch.setattr(app.time, "time", lambda: 100.0)
        test_client.get("/question")
        monkeypatch.setattr(app.time, "time", lambda: 100.0 + app.TIME_LIMIT + 0.1)
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.status_code == 200
        data = response.get_json()
        assert data["correct"] is False
        assert data["timed_out"] is True
        assert data["message"] == "Too slow!"
        assert data["lives"] == app.MAX_LIVES - 1

    def test_answer_at_time_limit_is_not_timed_out(self, started_game, monkeypatch):
        test_client, _ = started_game
        monkeypatch.setattr(app.time, "time", lambda: 100.0)
        test_client.get("/question")
        monkeypatch.setattr(app.time, "time", lambda: 100.0 + app.TIME_LIMIT)
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.status_code == 200
        assert response.get_json()["timed_out"] is False
        assert response.get_json()["correct"] is True


class TestLives:
    def test_lives_decrease_for_each_wrong_answer(self, started_game):
        test_client, _ = started_game
        for expected_lives in range(app.MAX_LIVES - 1, 0, -1):
            test_client.get("/question")
            response = test_client.post("/answer", json={"guess": "wrong"})
            assert response.get_json()["lives"] == expected_lives

    def test_game_over_on_last_wrong_answer(self, started_game):
        test_client, _ = started_game
        for _ in range(app.MAX_LIVES):
            test_client.get("/question")
            response = test_client.post("/answer", json={"guess": "wrong"})
        data = response.get_json()
        assert data["lives"] == 0
        assert data["game_over"] is True
        with test_client.session_transaction() as session:
            assert session["lives"] == 0

    def test_lives_do_not_decrease_for_correct_answer(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.get_json()["lives"] == app.MAX_LIVES


class TestStreaks:
    def test_first_correct_answer_starts_streak(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.get_json()["streak"] == 1

    def test_consecutive_correct_answers_increase_streak(self, started_game):
        test_client, _ = started_game
        for expected_streak in (1, 2, 3):
            test_client.get("/question")
            response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
            assert response.get_json()["streak"] == expected_streak

    def test_wrong_answer_resets_streak(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        test_client.post("/answer", json={"guess": "A Night at the Opera"})
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "wrong"})
        assert response.get_json()["streak"] == 0

    def test_correct_after_wrong_starts_new_streak(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        test_client.post("/answer", json={"guess": "wrong"})
        test_client.get("/question")
        response = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert response.get_json()["streak"] == 1


class TestInvalidRequests:
    def test_score_submission_requires_name(self, started_game):
        test_client, _ = started_game
        response = test_client.post("/scores", json={})
        assert response.status_code == 400
        assert "name" in response.get_json()["error"]

    def test_score_submission_without_json_is_rejected(self, started_game):
        test_client, _ = started_game
        response = test_client.post("/scores")
        assert response.status_code == 400
        assert "name" in response.get_json()["error"]

    def test_unknown_route_returns_404(self, client):
        test_client, _ = client
        response = test_client.get("/does-not-exist")
        assert response.status_code == 404


class TestSessionBehaviour:
    def test_session_preserves_score_between_requests(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        test_client.post("/answer", json={"guess": "A Night at the Opera"})
        with test_client.session_transaction() as session:
            assert session["score"] == 10
            assert session["streak"] == 1
            assert session["questions_asked"] == 1
        response = test_client.get("/question")
        data = response.get_json()
        assert data["score"] == 10
        assert data["streak"] == 1
        assert data["questions_asked"] == 1

    def test_new_game_resets_persisted_state(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        test_client.post("/answer", json={"guess": "A Night at the Opera"})
        test_client.post("/new-game")
        with test_client.session_transaction() as session:
            assert session["score"] == 0
            assert session["streak"] == 0
            assert session["questions_asked"] == 0
            assert session["lives"] == app.MAX_LIVES

    def test_current_question_is_not_reusable(self, started_game):
        test_client, _ = started_game
        test_client.get("/question")
        first = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        second = test_client.post("/answer", json={"guess": "A Night at the Opera"})
        assert first.status_code == 200
        assert second.status_code == 400
        assert "No active question" in second.get_json()["error"]
