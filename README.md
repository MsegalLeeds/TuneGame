# TuneGame

Flask + vanilla JavaScript music quiz using a local CSV and Spotify playback.

## Requirements

- Python 3.10+
- Spotify Developer application
- Spotify Premium for playback control
- A browser

## Setup

From the repository root:

    cd Server
    python -m venv .venv

Activate it, then:

    pip install -r requirements.txt

Create `Server/.env` locally using `.env.example`. Register the same Spotify redirect URI in your Spotify Developer application.

## Run the web app

Terminal 1:

    cd Server
    python app.py

Terminal 2, from the repository root:

    python -m http.server 8000 --directory Client

Open `http://localhost:8000`.

The frontend calls Flask at `http://localhost:5000`. Keep the hostname consistent (`localhost` vs `127.0.0.1`) when testing browser sessions.

## Run tests

From `Server`:

    pytest -q

Tests mock Spotify and use an in-memory DataFrame, so Spotify credentials and a Spotify device are not required.

## Security

Do not commit `.env`, Spotify secrets, session cookies, or other credentials. Credentials were previously present in the repository history; rotate the exposed Spotify client secret and Flask session secret before using this project again.

## API

- `POST /new-game` reset game state
- `GET /question?mode=mc|typed` create a question
- `POST /answer` submit an answer
- `POST /play-song?clip=true|false` play the current track
- `POST /pause` pause playback
- `GET /scores` read leaderboard
- `POST /scores` save the current score
