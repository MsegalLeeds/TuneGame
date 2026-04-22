import pytest
import pandas as pd
import spotipy
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Patch at import time so module-level code (sp = spotipy.Spotify(...),
# songGame = SongGame(), etc.) doesn't run for real.
# ---------------------------------------------------------------------------

SAMPLE_DATA = pd.DataFrame({
    "Song":   ["Bohemian Rhapsody", "Billie Jean", "Smells Like Teen Spirit"],
    "Album":  ["A Night at the Opera", "Thriller", "Nevermind"],
    "Artist": ["Queen", "Michael Jackson", "Nirvana"],
})


@pytest.fixture(autouse=True)
def mock_module_level_side_effects():
    """
    Prevent the module from connecting to Spotify or running the game loop
    when it is first imported.
    """
    with patch("spotipy.Spotify", return_value=MagicMock()), \
         patch("spotipy.oauth2.SpotifyOAuth", return_value=MagicMock()), \
         patch("pandas.read_csv", return_value=SAMPLE_DATA.copy()), \
         patch("builtins.input", return_value="A Night at the Opera"), \
         patch("random.choice", return_value=("Song", "Album", "Name the album that $ is on? ")):
        yield


@pytest.fixture
def game():
    """A SongGame instance pinned to the first row, with no real I/O."""
    from SongGame import SongGame
    with patch("pandas.read_csv", return_value=SAMPLE_DATA.copy()):
        g = SongGame()
    g.row = SAMPLE_DATA.iloc[[0]]   # pin to Bohemian Rhapsody / Queen
    return g


@pytest.fixture
def sp_mock(game):
    """Attach a fresh Spotify mock to the module and return it."""
    import SongGame as sg
    mock = MagicMock()
    mock.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:abc123"}]}}
    sg.sp = mock
    return mock


# ===========================================================================
# TestGetField
# ===========================================================================

class TestGetField:
    def test_get_song(self, game):
        assert game.get_field("Song") == "Bohemian Rhapsody"

    def test_get_album(self, game):
        assert game.get_field("Album") == "A Night at the Opera"

    def test_get_artist(self, game):
        assert game.get_field("Artist") == "Queen"

    def test_missing_column_raises(self, game):
        with pytest.raises(KeyError):
            game.get_field("Genre")


# ===========================================================================
# TestSampleRow
# ===========================================================================

class TestSampleRow:
    def test_returns_dataframe(self, game):
        assert isinstance(game.sample_row(), pd.DataFrame)

    def test_returns_single_row(self, game):
        assert len(game.sample_row()) == 1

    def test_row_comes_from_dataframe(self, game):
        assert game.sample_row().index[0] in game.dataFrame.index


# ===========================================================================
# TestGetLookupRow
# ===========================================================================

class TestGetLookupRow:
    def test_index_0(self, game):
        assert game.get_lookup_row(0) == ("Song", "Album", "Name the album that $ is on? ")

    def test_index_1(self, game):
        assert game.get_lookup_row(1) == ("Song", "Artist", "Name the artist who wrote $? ")

    def test_index_2(self, game):
        assert game.get_lookup_row(2) == ("Album", "Artist", "Name the artist who made $? ")

    def test_out_of_range_raises(self, game):
        with pytest.raises(IndexError):
            game.get_lookup_row(99)


# ===========================================================================
# TestFormatQuestions
# ===========================================================================

class TestFormatQuestions:
    def test_placeholder_replaced(self, game):
        assert game.format_questions("Thriller", "Name the album that $ is on? ") \
               == "Name the album that Thriller is on? "

    def test_no_placeholder_unchanged(self, game):
        assert game.format_questions("Queen", "Who made this album? ") \
               == "Who made this album? "

    def test_multiple_placeholders_all_replaced(self, game):
        assert game.format_questions("X", "$ and $") == "X and X"


# ===========================================================================
# TestPlaySong
# ===========================================================================

class TestPlaySong:
    def test_searches_with_correct_query(self, game, sp_mock):
        game.play_song()
        sp_mock.search.assert_called_once_with(
            q="track:Bohemian Rhapsody artist:Queen",
            type="track",
            limit=1,
        )

    def test_starts_playback_when_track_found(self, game, sp_mock):
        game.play_song()
        sp_mock.start_playback.assert_called_with(uris=["spotify:track:abc123"])

    def test_prints_message_when_track_not_found(self, game, sp_mock, capsys):
        sp_mock.search.return_value = {"tracks": {"items": []}}
        game.play_song()
        assert "not found" in capsys.readouterr().out.lower()

    def test_spotify_exception_caught_gracefully(self, game, sp_mock, capsys):
        # Second start_playback call raises (the duplicate call bug in the original)
        sp_mock.start_playback.side_effect = [
            None,
            spotipy.exceptions.SpotifyException(http_status=403, code=-1, msg="No device"),
        ]
        sp_mock.search.return_value = {"tracks": {"items": []}}
        game.play_song()   # must not raise
        assert "Wrong".lower() in capsys.readouterr().out.lower()


# ===========================================================================
# TestAskUserUnknownFromKnown
# ===========================================================================

SONG_TO_ALBUM = ("Song", "Album", "Name the album that $ is on? ")


class TestAskUserUnknownFromKnown:
    def test_correct_answer_pauses_playback(self, game, sp_mock):
        with patch.object(game, "play_song"), \
             patch("builtins.input", return_value="A Night at the Opera"):
            game.ask_user_unknown_from_known(SONG_TO_ALBUM)
        sp_mock.pause_playback.assert_called_once()

    def test_correct_answer_is_case_insensitive(self, game, sp_mock):
        with patch.object(game, "play_song"), \
             patch("builtins.input", return_value="a night at the opera"):
            game.ask_user_unknown_from_known(SONG_TO_ALBUM)
        sp_mock.pause_playback.assert_called_once()

    def test_wrong_answer_does_not_pause(self, game, sp_mock):
        # Two attempts: wrong then correct
        with patch.object(game, "play_song"), \
             patch("builtins.input", side_effect=["wrong", "A Night at the Opera"]):
            game.ask_user_unknown_from_known(SONG_TO_ALBUM)
        assert sp_mock.pause_playback.call_count == 1   # only paused on correct

    def test_question_contains_known_value(self, game, sp_mock):
        prompted = []
        with patch.object(game, "play_song"), \
             patch("builtins.input", side_effect=lambda p: prompted.append(p) or "A Night at the Opera"):
            game.ask_user_unknown_from_known(SONG_TO_ALBUM)
        assert "Bohemian Rhapsody" in prompted[0]

    def test_play_song_called_each_attempt(self, game, sp_mock):
        with patch.object(game, "play_song") as mock_play, \
             patch("builtins.input", side_effect=["wrong", "A Night at the Opera"]):
            game.ask_user_unknown_from_known(SONG_TO_ALBUM)
        assert mock_play.call_count == 2