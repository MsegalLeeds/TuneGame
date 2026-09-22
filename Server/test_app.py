import json
import os
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from SongGame import SongGame

DATA = pd.DataFrame({
    "Song": ["Bohemian Rhapsody", "Billie Jean", "Smells Like Teen Spirit", "Hotel California"],
    "Album": ["A Night at the Opera", "Thriller", "Nevermind", "Hotel California"],
    "Artist": ["Queen", "Michael Jackson", "Nirvana", "Eagles"],
})

@pytest.fixture
def game():
    g = SongGame(DATA)
    g.row = DATA.iloc[[0]]
    return g

def test_get_field_and_question(game):
    assert game.get_field("Song") == "Bohemian Rhapsody"
    assert game.format_questions("Thriller", "Name the album that $ is on?") == "Name the album that Thriller is on?"

@pytest.mark.parametrize("guess,answer,expected", [
    ("Queen", "Queen", True),
    (" queen ", "QUEEN", True),
    ("A Night at Opera", "A Night at the Opera", True),
    ("", "Queen", False),
    (None, "Queen", False),
])
def test_close_match(game, guess, answer, expected):
    assert game.is_close_match(guess, answer) is expected

def test_generate_choices_has_unique_correct_answer(game):
    choices = game.generate_choices("Queen", "Artist")
    assert len(choices) == 4
    assert choices.count("Queen") == 1
    assert len(set(choices)) == 4

def test_award_points_and_reset_streak(game):
    assert game.award_points(True) == 10
    assert game.award_points(True) == 15
    assert game.score == 25
    assert game.streak == 2
    assert game.award_points(False) == 0
    assert game.streak == 0

def test_play_song(game):
    spotify = MagicMock()
    spotify.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:test"}]}}
    assert game.play_song(spotify) is True
    spotify.start_playback.assert_called_once_with(uris=["spotify:track:test"])

def test_play_song_missing_track(game):
    spotify = MagicMock()
    spotify.search.return_value = {"tracks": {"items": []}}
    assert game.play_song(spotify) is False
    spotify.start_playback.assert_not_called()

def test_web_new_game_and_question(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SongGame", lambda: SongGame(DATA))
    monkeypatch.setattr(app_module, "get_album_art", lambda song, artist: None)
    monkeypatch.setattr(app_module.random, "choice", lambda items: items[0])
    client = app_module.app.test_client()
    assert client.post("/new-game").status_code == 200
    response = client.get("/question?mode=mc")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["mode"] == "mc"
    assert len(payload["choices"]) == 4
    assert payload["time_limit"] == 120

def test_web_correct_multiple_choice(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SongGame", lambda: SongGame(DATA))
    monkeypatch.setattr(app_module, "get_album_art", lambda song, artist: None)
    monkeypatch.setattr(app_module.random, "choice", lambda items: items[0])
    client = app_module.app.test_client()
    client.post("/new-game")
    question = client.get("/question?mode=mc").get_json()
    response = client.post("/answer", json={"guess": "A Night at the Opera"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["correct"] is True
    assert payload["points_earned"] == 10
    assert payload["score"] == 10
    assert payload["lives"] == 3

def test_web_rejects_answer_without_question():
    import app as app_module
    client = app_module.app.test_client()
    client.post("/new-game")
    assert client.post("/answer", json={"guess": "Queen"}).status_code == 400

def test_web_timeout_loses_life(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SongGame", lambda: SongGame(DATA))
    monkeypatch.setattr(app_module, "get_album_art", lambda song, artist: None)
    monkeypatch.setattr(app_module.random, "choice", lambda items: items[0])
    client = app_module.app.test_client()
    client.post("/new-game")
    client.get("/question?mode=typed")
    with client.session_transaction() as session:
        session["question_time"] = time.time() - app_module.TIME_LIMIT - 1
    payload = client.post("/answer", json={"guess": ""}).get_json()
    assert payload["timed_out"] is True
    assert payload["correct"] is False
    assert payload["lives"] == 2

def test_save_score_validation(tmp_path, monkeypatch):
    import app as app_module
    score_file = tmp_path / "scores.json"
    monkeypatch.setattr(app_module, "SCORES_FILE", str(score_file))
    app_module.save_score(" Alice ", 25, 2)
    assert json.loads(score_file.read_text())[0]["name"] == "Alice"
    with pytest.raises(ValueError):
        app_module.save_score(" ", 10, 1)
    with pytest.raises(ValueError):
        app_module.save_score("x" * 21, 10, 1)
