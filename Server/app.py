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

from SongGame import SongGame, get_spotify_client

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
SCORES_FILE = os.path.join(BASE_DIR, "scores.json")
TIME_LIMIT = 120
MAX_LIVES = 3
CLIP_START_MS = 30000
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:8000")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "local-development-secret"
app.config.update(
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=os.getenv("FLASK_COOKIE_SECURE", "false").lower() == "true",
)
CORS(app, supports_credentials=True, origins=[FRONTEND_ORIGIN])


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
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            scores = json.load(f)
        return scores if isinstance(scores, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_score(name: str, score: int, questions: int):
    name = str(name).strip()
    if not name:
        raise ValueError("Name cannot be empty.")
    if len(name) > 20:
        raise ValueError("Name must be 20 characters or fewer.")

    scores = load_scores()
    scores.append({
        "name": name,
        "score": int(score),
        "questions": int(questions),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    scores.sort(key=lambda item: item["score"], reverse=True)

    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(scores[:10], f, indent=2)


def get_album_art(song: str, artist: str, spotify=None) -> Optional[str]:
    try:
        spotify = spotify or get_spotify_client()
        results = spotify.search(
            q=f"track:{song} artist:{artist}", type="track", limit=1
        )
        tracks = results.get("tracks", {}).get("items", [])
        if tracks:
            images = tracks[0].get("album", {}).get("images", [])
            if images:
                return images[0].get("url")
    except (spotipy.exceptions.SpotifyException, RuntimeError):
        pass
    return None


def is_game_over() -> bool:
    return session.get("lives", MAX_LIVES) <= 0


def check_time_limit() -> bool:
    question_time = session.get("question_time")
    return not question_time or (time.time() - question_time) <= TIME_LIMIT


@app.route("/new-game", methods=["POST"])
def new_game():
    session.clear()
    session.update(lives=MAX_LIVES, score=0, streak=0, questions_asked=0)
    return jsonify(ok=True, message="Game reset", lives=MAX_LIVES, time_limit=TIME_LIMIT)


@app.route("/question", methods=["GET"])
def get_question():
    if is_game_over():
        return jsonify(error="Game over. Call /new-game to start again."), 400

    game = get_game()
    game.row = game.sample_row()
    known_field, unknown_field, template = random.choice(game.lookup)
    known = game.get_field(known_field)
    correct = game.get_field(unknown_field)
    use_mc = request.args.get("mode", "mc").lower() == "mc"
    song = game.get_field("Song")
    artist = game.get_field("Artist")

    session.update(
        question_time=time.time(),
        current_correct=correct,
        current_song=song,
        current_artist=artist,
        current_mode="mc" if use_mc else "typed",
    )

    response = {
        "question": game.format_questions(known, template),
        "mode": "mc" if use_mc else "typed",
        "questions_asked": game.questions_asked,
        "score": game.score,
        "streak": game.streak,
        "lives": session.get("lives", MAX_LIVES),
        "time_limit": TIME_LIMIT,
        "album_art": get_album_art(song, artist),
    }

    if use_mc:
        choices = game.generate_choices(correct, unknown_field)
        response["choices"] = choices
        session["choices"] = choices

    save_game(game)
    return jsonify(response)


@app.route("/answer", methods=["POST"])
def post_answer():
    if is_game_over():
        return jsonify(error="Game over. Call /new-game to start again."), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON request body required"), 400

    correct = session.get("current_correct")
    if correct is None:
        return jsonify(error="No active question. Call /question first."), 400

    guess = data.get("guess")
    if not isinstance(guess, str):
        return jsonify(error="A string 'guess' is required"), 400

    timed_out = not check_time_limit()
    game = get_game()

    if timed_out:
        is_correct = False
        result_message = "Too slow!"
    elif session.get("current_mode") == "mc":
        choices = session.get("choices", [])
        is_correct = guess in choices and guess == correct
        result_message = "Correct!" if is_correct else "Wrong!"
    else:
        is_correct = game.is_close_match(guess, correct)
        result_message = "Correct!" if is_correct else "Wrong!"

    lives = session.get("lives", MAX_LIVES)
    if not is_correct:
        lives = max(0, lives - 1)
        session["lives"] = lives

    game.questions_asked += 1
    earned = game.award_points(is_correct)
    save_game(game)

    for key in (
        "current_correct", "current_song", "current_artist",
        "current_mode", "choices", "question_time",
    ):
        session.pop(key, None)

    return jsonify(
        correct=is_correct,
        correct_answer=correct,
        message=result_message,
        timed_out=timed_out,
        points_earned=earned,
        score=game.score,
        streak=game.streak,
        lives=lives,
        questions_asked=game.questions_asked,
        game_over=lives <= 0,
    )


@app.route("/play-song", methods=["POST"])
def play_song():
    song = session.get("current_song")
    artist = session.get("current_artist")
    if not song or not artist:
        return jsonify(error="No active question"), 400

    clip_mode = request.args.get("clip", "true").lower() == "true"

    try:
        spotify = get_spotify_client()
        results = spotify.search(
            q=f"track:{song} artist:{artist}", type="track", limit=1
        )
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return jsonify(error="Track not found on Spotify"), 404

        spotify.start_playback(uris=[tracks[0]["uri"]])
        if clip_mode:
            spotify.seek_track(CLIP_START_MS)

        return jsonify(
            ok=True,
            song=song,
            artist=artist,
            clip_mode=clip_mode,
            seek_position_ms=CLIP_START_MS if clip_mode else 0,
        )
    except spotipy.exceptions.SpotifyException as exc:
        return jsonify(error="Spotify error", detail=str(exc)), 503
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503


@app.route("/pause", methods=["POST"])
def pause():
    try:
        get_spotify_client().pause_playback()
        return jsonify(ok=True)
    except (spotipy.exceptions.SpotifyException, RuntimeError) as exc:
        return jsonify(error="Spotify error", detail=str(exc)), 503


@app.route("/scores", methods=["GET"])
def get_scores():
    return jsonify(load_scores())


@app.route("/scores", methods=["POST"])
def post_score():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "name" not in data:
        return jsonify(error="A 'name' field is required"), 400

    try:
        game = get_game()
        save_score(data["name"], game.score, game.questions_asked)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, score=game.score)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
