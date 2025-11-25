import os
import json
from collections import Counter
from urllib.parse import urlencode, parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ================ CONFIG ================

CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]

# Use your Render domain here once deployed, or set via env
BASE_URL = os.environ.get("BASE_URL", "https://your-app-name.onrender.com")

REDIRECT_URI = BASE_URL + "/callback"

SCOPE = (
    "user-top-read user-library-read user-read-recently-played "
    "playlist-modify-private playlist-modify-public"
)

PLAYLIST_NAME = "Best 1000 All-Time Tracks"

auth_manager = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE
)

app = FastAPI()


@app.get("/login")
def login():
    url = auth_manager.get_authorize_url()
    return {"auth_url": url}


@app.get("/callback")
async def callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    if not code:
        return HTMLResponse("<h1>Error: No code provided</h1>")

    # Exchange code for token
    token_info = auth_manager.get_access_token(code)
    access_token = token_info["access_token"]

    # Show simple HTML page or redirect somewhere
    return HTMLResponse(f"""
        <h2>Authenticated!</h2>
        <p>Your access token: <code>{access_token}</code></p>
        <p>You can now go back to the app and use the token.</p>
    """)


@app.post("/generate")
async def generate(data: dict):
    # data should include {"code": "...", "files": [...]}
    code = data.get("code")
    files = data.get("files", [])

    if not code:
        return {"status": "error", "message": "no auth code"}

    token_info = auth_manager.get_access_token(code)
    sp = spotipy.Spotify(auth=token_info["access_token"])
    user = sp.current_user()

    all_tracks = []
    for file_data in files:
        # assume file_data is a JSON-string already
        all_tracks.extend(json.loads(file_data))

    track_playtime = Counter()
    for entry in all_tracks:
        name = entry.get("master_metadata_track_name")
        artist = entry.get("master_metadata_album_artist_name")
        ms = entry.get("ms_played", 0)
        uri = entry.get("spotify_track_uri")

        if not name or not artist or ms < 30_000:
            continue

        key = uri if uri else f"{name} - {artist}"
        track_playtime[key] += ms

    top = [t for t, _ in track_playtime.most_common(1000)]

    matched_ids = []
    for t in top:
        if t.startswith("spotify:track:"):
            matched_ids.append(t.split(":")[-1])
        else:
            name, artist = t.split(" - ", 1) if " - " in t else (t, "")
            results = sp.search(f"track:{name} artist:{artist}", type="track", limit=1)
            items = results["tracks"]["items"]
            if items:
                matched_ids.append(items[0]["id"])

    playlist = sp.user_playlist_create(
        user["id"], PLAYLIST_NAME, public=False,
        description="Top 1000 songs"
    )
    for i in range(0, len(matched_ids), 100):
        sp.playlist_add_items(playlist["id"], matched_ids[i:i+100])

    return {"status": "success", "playlist_url": playlist["external_urls"]["spotify"]}
