import os
import json
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr

# --------------------------- #
# Spotify Credentials
# --------------------------- #

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SPOTIFY_TOKENS = {"access_token": None, "user_id": None}


# --------------------------- #
# OAuth Helpers
# --------------------------- #

def get_auth_url():
    scopes = (
        "playlist-modify-public playlist-modify-private "
        "user-library-read user-read-private"
    )
    return (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scopes}"
    )


def get_tokens(code):
    url = "https://accounts.spotify.com/api/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    return requests.post(url, data=data).json()


def get_user_profile(token):
    resp = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    return resp.json() if resp.status_code == 200 else None


def check_login_status():
    return "✅ Logged in!" if SPOTIFY_TOKENS.get("access_token") else "❌ Not logged in"


# --------------------------- #
# OAuth Callback
# --------------------------- #

@app.get("/spotify/callback")
def spotify_callback(code: str):
    tokens = get_tokens(code)

    if "access_token" in tokens:
        SPOTIFY_TOKENS["access_token"] = tokens["access_token"]

        profile = get_user_profile(tokens["access_token"])
        if profile:
            SPOTIFY_TOKENS["user_id"] = profile["id"]

        # FIXED popup close
        return """
        <html><body>
        <script>
        setTimeout(() => {
            window.open('', '_self');
            window.close();
        }, 300);
        </script>
        Authentication successful! You may close this tab.
        </body></html>
        """

    return {"error": "Failed to authenticate.", "tokens": tokens}


# --------------------------- #
# Utility: Load JSON file
# --------------------------- #

def load_json_file(f):
    """Handles both file paths and raw binary from Gradio 5.1"""
    if isinstance(f, str):
        # Gradio gave us a file path
        with open(f, "rb") as infile:
            file_bytes = infile.read()
    elif isinstance(f, bytes):
        file_bytes = f
    else:
        return None

    try:
        return json.loads(file_bytes.decode("utf-8"))
    except Exception:
        return None


# --------------------------- #
# Playlist Generator
# --------------------------- #

def generate_playlist(files):
    access_token = SPOTIFY_TOKENS.get("access_token")
    user_id = SPOTIFY_TOKENS.get("user_id")

    if not access_token:
        return "❌ Please login first."

    if not files:
        return "❌ No files uploaded."

    all_tracks = []

    for f in files:
        data = load_json_file(f)
        if not data:
            continue

        tracks = []

        if isinstance(data, dict) and "tracks" in data:
            tracks = data["tracks"]
        elif isinstance(data, list):
            tracks = data

        for t in tracks:
            uri = t.get("spotify_track_uri")
            ms_played = t.get("ms_played", 0)
            if uri:
                all_tracks.append((uri, ms_played))

    if not all_tracks:
        return "❌ No valid track URIs found."

    # Remove duplicates (keep max playtime)
    best = {}
    for uri, ms in all_tracks:
        if uri not in best or ms > best[uri]:
            best[uri] = ms

    # Sort by playtime
    sorted_tracks = sorted(best.items(), key=lambda x: x[1], reverse=True)

    # Cap at 1000
    track_uris = [uri for uri, _ in sorted_tracks[:1000]]

    # Create playlist
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "name": "Top 1000 Playlist",
            "description": "Automatically generated",
            "public": True
        }
    )

    if create_resp.status_code != 201:
        return f"❌ Playlist creation failed: {create_resp.text}"

    playlist_id = create_resp.json()["id"]

    # Upload in chunks of 100
    for i in range(0, len(track_uris), 100):
        chunk = track_uris[i:i + 100]
        resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"uris": chunk}
        )
        if resp.status_code != 201:
            return f"❌ Track add failed: {resp.text}"

    return f"🎉 Playlist created with {len(track_uris)} tracks!"


# --------------------------- #
# Top 50 Artists
# --------------------------- #

def get_top_artists(files):
    all_tracks = []

    for f in files:
        data = load_json_file(f)
        if not data:
            continue

        tracks = data.get("tracks", data if isinstance(data, list) else [])
        for t in tracks:
            artists = t.get("artist_name")
            ms = t.get("ms_played", 0)

            if artists:
                all_tracks.append((artists, ms))

    stats = {}
    for artist, ms in all_tracks:
        stats[artist] = stats.get(artist, 0) + ms

    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:50]

    html = "<h2>Top 50 Artists</h2><ul>"
    for name, ms in top:
        hours = round(ms / (1000 * 60 * 60), 2)
        html += f"<li><b>{name}</b> — {hours}h</li>"
    html += "</ul>"

    return html


# --------------------------- #
# Top 50 Albums
# --------------------------- #

def get_top_albums(files):
    all_tracks = []

    for f in files:
        data = load_json_file(f)
        if not data:
            continue

        tracks = data.get("tracks", data if isinstance(data, list) else [])
        for t in tracks:
            album = t.get("album_name")
            ms = t.get("ms_played", 0)

            if album:
                all_tracks.append((album, ms))

    stats = {}
    for alb, ms in all_tracks:
        stats[alb] = stats.get(alb, 0) + ms

    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:50]

    html = "<h2>Top 50 Albums</h2><ul>"
    for name, ms in top:
        hours = round(ms / (1000 * 60 * 60), 2)
        html += f"<li><b>{name}</b> — {hours}h</li>"
    html += "</ul>"

    return html


# --------------------------- #
# Gradio UI
# --------------------------- #

with gr.Blocks(title="Spotify Extended App") as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist & Stats Dashboard")

    with gr.Tabs():

        with gr.Tab("Playlist Generator"):
            login_btn = gr.Button("Login with Spotify")
            status = gr.Textbox(value=check_login_status(), interactive=False)
            refresh = gr.Button("Refresh Status")
            refresh.click(check_login_status, None, status)

            login_btn.click(
                None,
                None,
                None,
                js=f"window.open('{get_auth_url()}', '_blank')"
            )

            files = gr.File(file_types=[".json"], file_count="multiple")
            submit = gr.Button("Generate Playlist")
            result = gr.Textbox()
            submit.click(generate_playlist, files, result)

        with gr.Tab("Top Artists"):
            artist_files = gr.File(file_types=[".json"], file_count="multiple")
            artist_btn = gr.Button("Generate Top Artists")
            artist_html = gr.HTML()
            artist_btn.click(get_top_artists, artist_files, artist_html)

        with gr.Tab("Top Albums"):
            album_files = gr.File(file_types=[".json"], file_count="multiple")
            album_btn = gr.Button("Generate Top Albums")
            album_html = gr.HTML()
            album_btn.click(get_top_albums, album_files, album_html)

app = gr.mount_gradio_app(app, gradio_app, path="/")
