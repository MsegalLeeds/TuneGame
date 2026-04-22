import random

import pandas as pd
import spotipy
from spotipy.oauth2 import SpotifyOAuth

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id="3e900ce8ebd74e61b1a67b75e1339d25",
    client_secret="17e5982db4f54c8e8b24d6ee624708b1",
    redirect_uri="https://example.com/callback",
    scope="user-modify-playback-state user-read-playback-state"
))


class SongGame:

    lookup = [
        ("Song", "Album", "Name the album that $ is on? "),
        ("Song", "Artist", "Name the artist who wrote $? "),
        ("Album", "Artist", "Name the artist who made $? "),
        ]

    def __init__(self):
        self.dataFrame = pd.read_csv('music.csv')
        self.row = self.dataFrame.sample(1)

    def sample_row(self):
        return self.dataFrame.sample(1)

    def get_field(self, key) -> str:
        return self.row[key].values[0]

    def get_lookup_row(self, key):
        return self.lookup[key]

    def format_questions(self, known, question) -> str:
        question = question.replace("$", known)
        return question

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

    def ask_user_unknown_from_known(self, lookupRow):
        known = self.get_field(lookupRow[0])
        unknown = self.get_field(lookupRow[1])
        question = self.format_questions(known, lookupRow[2])
        self.play_song()
        user_guess = input(question)
        if user_guess.lower() == unknown.lower():
            sp.pause_playback()
            print(f" Yay!")
        else:
            print(f"Wrong! Try again")
            self.ask_user_unknown_from_known(lookupRow)


songGame = SongGame()
lookupRow = random.choice(songGame.lookup)
songGame.ask_user_unknown_from_known(lookupRow)