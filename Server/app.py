import json
import os
import random
import time
from datetime import datetime
from typing import Optional

import spotipy
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session
from flask_cors import CORS

from SongGame import SongGame, sp

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "tunegame-secret")
CORS(app, supports_credentials=True)

SCORES_FILE = "scores.json"
TIME_LIMIT = 120        # seconds to answer before time's up
MAX_LIVES = 3          # wrong answers before game over
CLIP_START_MS = 30000  # seek to 30 seconds for clip mode


# ── helpers ───────────────────────────────────────────────────────────────────

def get_game() -> SongGame:
    game = SongGame()
    game.score = session.get("score", 0)
    game.streak = session.get("streak", 0)
    game.questions_asked = session.get("questions_asked", 0)
    return game


def save_game(game: SongGame):
    session["score"] = game.score
    session["streak"] = game.streak
    session["questions_asked"] = game.questions_asked


def load_scores() -> list:
    if not os.path.exists(SCORES_FILE):
        return []
    with open(SCORES_FILE, "r") as f:
        return json.load(f)


def save_score(name: str, score: int, questions: int):
    scores = load_scores()
    scores.append({
        "name": name,
        "score": score,
        "questions": questions,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    scores.sort(key=lambda x: x["score"], reverse=True)
    scores = scores[:10]
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2)


def get_album_art(song: str, artist: str) -> Optional[str]:
    """Search Spotify and return the album art URL, or None if not found."""
    try:
        results = sp.search(q=f"track:{song} artist:{artist}", type="track", limit=1)
        tracks = results["tracks"]["items"]
        if tracks:
            images = tracks[0]["album"]["images"]
            if images:
                return images[0]["url"]  # first image is highest resolution
    except spotipy.exceptions.SpotifyException:
        pass
    return None


def is_game_over() -> bool:
    return session.get("lives", MAX_LIVES) <= 0


def check_time_limit() -> bool:
    """Returns True if the player is still within the time limit."""
    question_time = session.get("question_time")
    if not question_time:
        return True
    return (time.time() - question_time) <= TIME_LIMIT


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/new-game", methods=["POST"])
def new_game():
    session.clear()
    session["lives"] = MAX_LIVES
    session["score"] = 0
    session["streak"] = 0
    session["questions_asked"] = 0
    return jsonify({
        "ok": True,
        "message": "Game reset",
        "lives": MAX_LIVES,
        "time_limit": TIME_LIMIT,
    })


@app.route("/question", methods=["GET"])
def get_question():
    if is_game_over():
        return jsonify({"error": "Game over. Call /new-game to start again."}), 400

    game = get_game()
    game.row = game.sample_row()
    lookup_row = random.choice(game.lookup)
    known_field, unknown_field, template = lookup_row
    known = game.get_field(known_field)
    correct = game.get_field(unknown_field)
    question = game.format_questions(known, template)
    use_mc = request.args.get("mode", "mc") == "mc"
    song = game.get_field("Song")
    artist = game.get_field("Artist")

    # fetch album art from Spotify
    album_art = get_album_art(song, artist)

    # stamp the time so /answer can check it
    session["question_time"] = time.time()
    session["current_correct"] = correct
    session["current_song"] = song
    session["current_artist"] = artist

    response = {
        "question": question,
        "mode": "mc" if use_mc else "typed",
        "questions_asked": game.questions_asked,
        "score": game.score,
        "streak": game.streak,
        "lives": session.get("lives", MAX_LIVES),
        "time_limit": TIME_LIMIT,
        "album_art": album_art,
    }

    if use_mc:
        choices = game.generate_choices(correct, unknown_field)
        response["choices"] = choices
        session["correct_index"] = choices.index(correct)

    save_game(game)
    return jsonify(response)


@app.route("/answer", methods=["POST"])
def post_answer():
    if is_game_over():
        return jsonify({"error": "Game over. Call /new-game to start again."}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    correct = session.get("current_correct")
    if not correct:
        return jsonify({"error": "No active question. Call /question first."}), 400

    # check time limit
    timed_out = not check_time_limit()
    guess = data.get("guess", "")
    game = get_game()

    if timed_out:
        is_correct = False
        result_message = "Too slow!"
    else:
        is_correct = game.is_close_match(guess, correct)
        result_message = "Correct!" if is_correct else "Wrong!"

    # update lives
    lives = session.get("lives", MAX_LIVES)
    if not is_correct:
        lives -= 1
        session["lives"] = lives

    game.questions_asked += 1
    game.award_points(is_correct)
    save_game(game)
    session.pop("current_correct", None)
    session.pop("question_time", None)

    game_over = lives <= 0

    return jsonify({
        "correct": is_correct,
        "correct_answer": correct,
        "message": result_message,
        "timed_out": timed_out,
        "score": game.score,
        "streak": game.streak,
        "lives": lives,
        "questions_asked": game.questions_asked,
        "game_over": game_over,
    })


@app.route("/play-song", methods=["POST"])
def play_song():
    song = session.get("current_song")
    artist = session.get("current_artist")
    clip_mode = request.args.get("clip", "true") == "true"

    if not song or not artist:
        return jsonify({"error": "No active question"}), 400

    game = get_game()
    game.row = game.dataFrame[game.dataFrame["Song"] == song].head(1)

    if game.row.empty:
        return jsonify({"error": f"Song '{song}' not found in dataset"}), 404

    try:
        results = sp.search(q=f"track:{song} artist:{artist}", type="track", limit=1)
        tracks = results["tracks"]["items"]

        if not tracks:
            return jsonify({"error": "Track not found on Spotify"}), 404

        uri = tracks[0]["uri"]
        sp.start_playback(uris=[uri])

        if clip_mode:
            # small delay to let playback start before seeking
            time.sleep(0.5)
            sp.seek_track(CLIP_START_MS)

        return jsonify({
            "ok": True,
            "song": song,
            "artist": artist,
            "clip_mode": clip_mode,
            "seek_position_ms": CLIP_START_MS if clip_mode else 0,
        })

    except spotipy.exceptions.SpotifyException as e:
        return jsonify({"error": "Spotify error", "detail": str(e)}), 503


@app.route("/pause", methods=["POST"])
def pause():
    try:
        sp.pause_playback()
        return jsonify({"ok": True})
    except spotipy.exceptions.SpotifyException as e:
        return jsonify({"error": "Spotify error", "detail": str(e)}), 503


@app.route("/scores", methods=["GET"])
def get_scores():
    return jsonify(load_scores())


@app.route("/scores", methods=["POST"])
def post_score():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "A 'name' field is required"}), 400

    game = get_game()
    save_score(
        name=data["name"],
        score=game.score,
        questions=game.questions_asked,
    )
    return jsonify({"ok": True, "score": game.score})


if __name__ == "__main__":
    app.run(debug=True)