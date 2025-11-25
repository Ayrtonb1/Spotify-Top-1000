import os
import json
from collections import Counter
from urllib.parse import urlencode

import gradio as gr
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from fastapi import FastAPI, Request
from starlette.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.wsgi import WSGIMiddleware

# ================================================================
# CONFIG
# ================================================================
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

BASE_URL = "https://spotify-top-1000.onrender.com"  # your Render URL
REDIRECT_URI = f"{BASE_URL}/callback"

SCOPE = (
    "user-top-read user-library-read user-read-recently-played "
    "playlist-modify-private playlist-modify-public"
)

PLAYLIST_NAME = "Best 1000 All-Time Tracks"

# ================================================================
# FASTAPI — Backend for OAuth
# ================================================================
app = FastAPI()

# temporary storage — persisted per session in Gradio
oauth_codes = {}   # maps session_token → auth code


@app.get("/login")
def login():
    """Redirects user to Spotify OAuth login."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    return RedirectResponse(url)


@app.get("/callback")
def callback(request: Request):
    """Spotify redirects here. Extract ?code= and save it."""
    params = dict(request.query_params)
    code = params.get("code")

    if not code:
        return HTMLResponse("<h1>❌ No authorization code received.</h1>")

    # Store code in memory under a short token
    session_token = os.urandom(8).hex()
    oauth_codes[session_token] = code

    return HTMLResponse(f"""
        <h1>🎉 Spotify Login Successful!</h1>
        <p>Return to the app. Your authentication is complete.</p>
        <p>Copy this session token into the Gradio app:</p>
        <b>{session_token}</b>
    """)

# ================================================================
# PLAYLIST GENERATOR
# ================================================================
def generate_playlist(session_token, files):
    # ensure files is a list
    if not isinstance(files, list):
        files = [files] if files else []

    if not session_token:
        return "❌ Please authenticate first.", None

    if not files:
        return "❌ No files uploaded.", None

    auth_code = oauth_codes.get(session_token)
    if not auth_code:
        return "❌ Session token not found or expired.", None

    try:
        auth_manager = SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
        )

        token_info = auth_manager.get_access_token(auth_code, check_cache=False)
        sp = spotipy.Spotify(auth=token_info["access_token"])
        user = sp.current_user()

        logs = [f"✅ Logged in as {user['display_name']}"]

        # Load all JSON streaming history files
        all_tracks = []
        for f in files:
            if isinstance(f, bytes):
                all_tracks.extend(json.loads(f.decode("utf-8")))
            else:
                all_tracks.extend(json.load(f))
        logs.append(f"📂 Loaded {len(all_tracks):,} plays.")

        # Count playtime
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

        top_tracks = [t for t, _ in track_playtime.most_common(1000)]
        logs.append(f"🎧 Found {len(top_tracks)} top tracks.")

        matched_ids = []
        for t in top_tracks:
            if t.startswith("spotify:track:"):
                matched_ids.append(t.split(":")[-1])
            else:
                name, artist = t.split(" - ", 1)
                results = sp.search(f"track:{name} artist:{artist}", type="track")
                items = results["tracks"]["items"]
                if items:
                    matched_ids.append(items[0]["id"])

        # Create playlist
        playlist = sp.user_playlist_create(
            user["id"],
            PLAYLIST_NAME,
            public=False,
            description="Top 1000 songs ranked by total playtime.",
        )

        for i in range(0, len(matched_ids), 100):
            sp.playlist_add_items(playlist["id"], matched_ids[i:i+100])

        url = playlist["external_urls"]["spotify"]
        logs.append(f"🎉 Playlist created: {url}")

        return "\n".join(logs), f"<a href='{url}' target='_blank'>{url}</a>"

    except Exception as e:
        return f"❌ Error: {e}", None

# ================================================================
# GRADIO UI
# ================================================================
with gr.Blocks(title="Spotify Playlist Builder") as gradio_app:

    gr.Markdown("# 🎧 Spotify Top 1000 Playlist Generator\nMade dark, modern, simple.")

    gr.Markdown("### Step 1 — Log in")
    gr.Markdown(f"[🔐 **Click here to log in with Spotify**]({BASE_URL}/login)")

    session_token = gr.Textbox(
        label="Paste session token from /callback page",
        placeholder="e.g., a3f91b7c2d8e4d1a"
    )

    gr.Markdown("### Step 2 — Upload your Streaming History JSON files")
    files = gr.File(file_count="multiple", file_types=[".json"], type="binary")

    run_btn = gr.Button("🎶 Generate Playlist")
    logs = gr.Textbox(lines=25, label="Status")
    link = gr.HTML()

    run_btn.click(generate_playlist,
                  inputs=[session_token, files],
                  outputs=[logs, link])

# ================================================================
# Mount Gradio onto FastAPI
# ================================================================
app.mount("/", WSGIMiddleware(gradio_app))
