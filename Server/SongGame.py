import difflib
import os
import random
from typing import Optional

import pandas as pd
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

ERROR_THRESHOLD = 0.6
POINTS_PER_QUESTION = 10
STREAK_BONUS = 5
CSV_PATH = os.path.join(os.path.dirname(__file__), "music.csv")


def get_spotify_client():
    """Create a Spotify client lazily so importing this module is testable."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    if not all((client_id, client_secret, redirect_uri)):
        raise RuntimeError(
            "Spotify credentials are not configured. "
            "Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET and SPOTIFY_REDIRECT_URI."
        )

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-modify_playback-state user-read-playback-state",
        )
    )


class SongGame:
    lookup = [
        ("Song", "Album", "Name the album that $ is on?"),
        ("Song", "Artist", "Name the artist who wrote $?"),
        ("Album", "Artist", "Name the artist who made $?"),
    ]

    def __init__(self, data_frame: Optional[pd.DataFrame] = None):
        self.dataFrame = data_frame.copy() if data_frame is not None else pd.read_csv(CSV_PATH)
        required = {"Song", "Album", "Artist"}
        missing = required.difference(self.dataFrame.columns)
        if missing:
            raise ValueError(f"Music data is missing columns: {sorted(missing)}")
        if self.dataFrame.empty:
            raise ValueError("Music data must contain at least one song.")
        self.row = self.sample_row()
        self.score = 0
        self.streak = 0
        self.questions_asked = 0

    def sample_row(self):
        return self.dataFrame.sample(n=1)

    def get_field(self, key) -> str:
        if self.row.empty:
            raise ValueError("No song is currently selected.")
        return str(self.row.iloc[0][key])

    def get_lookup_row(self, key):
        return self.lookup[key]

    def format_questions(self, known, question) -> str:
        return question.replace("$", str(known))

    def is_close_match(self, guess: str, answer: str) -> bool:
        if guess is None or answer is None:
            return False
        guess = str(guess).strip().lower()
        answer = str(answer).strip().lower()
        if not guess or not answer:
            return False
        return difflib.SequenceMatcher(None, guess, answer).ratio() >= ERROR_THRESHOLD

    def generate_choices(self, correct_answer: str, field: str) -> list[str]:
        values = self.dataFrame[field].dropna().astype(str)
        values = values[values.str.casefold() != str(correct_answer).casefold()]
        values = values.drop_duplicates().tolist()
        wrong = random.sample(values, k=min(3, len(values)))
        choices = wrong + [str(correct_answer)]
        random.shuffle(choices)
        return choices

    def display_choices(self, choices: list[str]) -> None:
        for label, choice in zip("ABCD", choices):
            print(f"  {label}: {choice}")

    def award_points(self, correct: bool) -> int:
        if not correct:
            self.streak = 0
            return 0
        self.streak += 1
        earned = POINTS_PER_QUESTION + (self.streak - 1) * STREAK_BONUS
        self.score += earned
        return earned

    def play_song(self, spotify=None) -> bool:
        spotify = spotify or get_spotify_client()
        results = spotify.search(
            q=f"track:{self.get_field('Song')} artist:{self.get_field('Artist')}",
            type="track",
            limit=1,
        )
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return False
        spotify.start_playback(uris=[tracks[0]["uri"]])
        return True

    def ask_question(self, lookup_row, multiple_choices: bool = True, spotify=None):
        known_field, unknown_field, question_template = lookup_row
        known = self.get_field(known_field)
        correct = self.get_field(unknown_field)
        question = self.format_questions(known, question_template)
        self.questions_asked += 1

        try:
            self.play_song(spotify)
        except (spotipy.exceptions.SpotifyException, RuntimeError) as exc:
            print(f"Spotify unavailable: {exc}")

        print(f"\nQuestion {self.questions_asked}: {question}")

        if multiple_choices:
            choices = self.generate_choices(correct, unknown_field)
            self.display_choices(choices)
            while True:
                raw = input("Your answer? (A/B/C/D): ").strip().upper()
                if raw in "ABCD"[:len(choices)]:
                    break
                print("Invalid answer! Try again.")
            is_correct = choices["ABCD".index(raw)] == correct
            if is_correct:
                print(f"Correct! +{self.award_points(True)} | Score: {self.score}")
            else:
                self.award_points(False)
                print(f"Wrong! Correct answer: {correct}")
            return is_correct

        for _ in range(3):
            guess = input("Your answer: ")
            if self.is_close_match(guess, correct):
                self.award_points(True)
                return True
            print("Wrong, try again!")
        self.award_points(False)
        print(f"Out of attempts. Correct answer: {correct}")
        return False

    def print_summary(self):
        print(f"\n{'=' * 30}")
        print("Song Game Results:")
        print(f"Score: {self.score}")
        print(f"Questions answered: {self.questions_asked}")
        print(f"Current streak: {self.streak}")
        print(f"{'=' * 30}")


if __name__ == "__main__":
    game = SongGame()
    for _ in range(5):
        game.row = game.sample_row()
        game.ask_question(random.choice(game.lookup), multiple_choices=random.choice([True, False]))
    game.print_summary()
