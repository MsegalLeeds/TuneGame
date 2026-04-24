import json
import os
import random
from datetime import datetime

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
    scores = scores[:10]  # keep top 10
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2)


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/new-game", methods=["POST"])
def new_game():
    session.clear()
    return jsonify({"ok": True, "message": "Game reset"})


@app.route("/question", methods=["GET"])
def get_question():
    game = get_game()
    game.row = game.sample_row()
    lookup_row = random.choice(game.lookup)
    known_field, unknown_field, template = lookup_row
    known = game.get_field(known_field)
    correct = game.get_field(unknown_field)
    question = game.format_questions(known, template)
    use_mc = request.args.get("mode", "mc") == "mc"

    response = {
        "question": question,
        "mode": "mc" if use_mc else "typed",
        "questions_asked": game.questions_asked,
        "score": game.score,
        "streak": game.streak,
    }

    if use_mc:
        choices = game.generate_choices(correct, unknown_field)
        response["choices"] = choices
        # store index so the answer check doesn't expose correct in the response
        session["correct_index"] = choices.index(correct)

    session["current_correct"] = correct
    session["current_song"] = game.get_field("Song")
    session["current_artist"] = game.get_field("Artist")
    save_game(game)
    return jsonify(response)


@app.route("/answer", methods=["POST"])
def post_answer():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    guess = data.get("guess", "")
    correct = session.get("current_correct")

    if not correct:
        return jsonify({"error": "No active question. Call /question first."}), 400

    game = get_game()
    is_correct = game.is_close_match(guess, correct)
    game.award_points(is_correct)
    save_game(game)

    # clear current question so the same question can't be answered twice
    session.pop("current_correct", None)

    return jsonify({
        "correct": is_correct,
        "correct_answer": correct,
        "score": game.score,
        "streak": game.streak,
        "questions_asked": game.questions_asked,
    })


@app.route("/play-song", methods=["POST"])
def play_song():
    song = session.get("current_song")
    artist = session.get("current_artist")

    if not song or not artist:
        return jsonify({"error": "No active question"}), 400

    game = get_game()
    game.row = game.dataFrame[game.dataFrame["Song"] == song].head(1)

    if game.row.empty:
        return jsonify({"error": f"Song '{song}' not found in dataset"}), 404

    try:
        game.play_song()
        return jsonify({"ok": True, "song": song, "artist": artist})
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