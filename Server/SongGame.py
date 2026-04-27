import random
import difflib
import os

import pandas as pd
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope="user-modify-playback-state user-read-playback-state"
))

ERROR_THRESHOLD = 0.6
POINTS_PER_QUESTION = 10
STREAK_BONUS = 5

CSV_PATH = os.path.join(os.path.dirname(__file__), "music.csv")


class SongGame:

    lookup = [
        ("Song", "Album", "Name the album that $ is on? "),
        ("Song", "Artist", "Name the artist who wrote $? "),
        ("Album", "Artist", "Name the artist who made $? "),
    ]

    def __init__(self):
        self.dataFrame = pd.read_csv(CSV_PATH)
        self.row = self.dataFrame.sample(1)
        self.score = 0
        self.streak = 0
        self.questions_asked = 0

    def sample_row(self):
        return self.dataFrame.sample(1)

    def get_field(self, key) -> str:
        return self.row[key].values[0]

    def get_lookup_row(self, key):
        return self.lookup[key]

    def format_questions(self, known, question) -> str:
        return question.replace("$", known)

    def is_close_match(self, guess: str, answer: str) -> bool:
        ratio = difflib.SequenceMatcher(
            None, guess.strip().lower(), answer.strip().lower()
        ).ratio()
        return ratio >= ERROR_THRESHOLD

    def generate_choices(self, correct_answer: str, field: str) -> list[str]:
        other_rows = self.dataFrame[
            self.dataFrame[field].str.lower() != correct_answer.lower()
        ]
        wrong = other_rows[field].drop_duplicates().sample(min(3, len(other_rows))).tolist()
        choices = wrong + [correct_answer]
        random.shuffle(choices)
        return choices

    def display_choices(self, choices: list[str]) -> None:
        labels = ["A", "B", "C", "D"]
        for label, choice in zip(labels, choices):
            print(f"  {label}: {choice}")

    def award_points(self, correct: bool) -> None:
        if correct:
            self.streak += 1
            earned = POINTS_PER_QUESTION + (self.streak - 1) * STREAK_BONUS
            self.score += earned
            bonus_msg = f" (+{(self.streak - 1) * STREAK_BONUS} streak bonus)" if self.streak > 1 else ""
            print(f"Correct! +{POINTS_PER_QUESTION}{bonus_msg} | Score: {self.score}")
        else:
            self.streak = 0

    def play_song(self):
        song = self.get_field("Song")
        artist = self.get_field("Artist")
        results = sp.search(q=f"track:{song} artist:{artist}", type="track", limit=1)
        tracks = results['tracks']['items']
        if tracks:
            uri = tracks[0]['uri']
            try:
                sp.start_playback(uris=[uri])
            except spotipy.exceptions.SpotifyException:
                print("No active Spotify device found. Please open Spotify first!")
        else:
            print("Track not found on Spotify")

    def ask_question(self, lookupRow, multiple_choices: bool = True):
        known_field, unknown_field, question_template = lookupRow
        known = self.get_field(known_field)
        correct = self.get_field(unknown_field)
        question = self.format_questions(known, question_template)

        self.questions_asked += 1
        print(f"\nQuestion {self.questions_asked}")
        self.play_song()

        if multiple_choices:
            choices = self.generate_choices(correct, unknown_field)
            labels = ["A", "B", "C", "D"]
            correct_label = labels[choices.index(correct)]
            print(question)
            self.display_choices(choices)
            while True:
                raw = input("Your answer? (A/B/C/D): ").strip().upper()
                if raw in labels:
                    break
                print("Invalid answer! Try again.")
            if raw == correct_label:
                self.award_points(correct=True)
            else:
                print(f"WRONG! Correct answer: {correct_label}) {correct}")
                self.award_points(correct=False)
        else:
            print(question)
            attempts = 0
            allowed_attempts = 3
            while attempts <= allowed_attempts:
                guess = input("Your answer: ")
                if self.is_close_match(guess, correct):
                    if guess.strip().lower() != correct.strip().lower():
                        print(f"Close enough. The correct answer is {correct}")
                    self.award_points(correct=True)
                    break
                else:
                    print("Close, try again!")
                    attempts += 1

    def print_summary(self):
        print(f"\n{'=' * 30}")
        print(f"\nSong Game Results:")
        print(f"\nScore: {self.score}")
        print(f"\nQuestions answered: {self.questions_asked}")
        print(f"\nBest Streak: {self.streak}")
        print(f"\n{'=' * 30}")


if __name__ == "__main__":
    NUM_ROUNDS = 5
    game = SongGame()
    for _ in range(NUM_ROUNDS):
        game.row = game.sample_row()
        lookupRow = random.choice(game.lookup)
        use_mc = random.choice([True, False])
        game.ask_question(lookupRow, multiple_choices=use_mc)
    game.print_summary()