import os
import json
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr

# ---------------------------
# Spotify Credentials
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store access token in memory
SPOTIFY_TOKENS = {"access_token": None, "user_id": None}

# ---------------------------
# Spotify Auth Helpers
# ---------------------------
def get_auth_url():
    scopes = "playlist-modify-public playlist-modify-private user-library-read"
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
    resp = requests.post(url, data=data)
    return resp.json()

def get_user_profile(token):
    resp = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code == 200:
        return resp.json()
    return None

def check_login_status():
    return "✅ Logged in!" if SPOTIFY_TOKENS.get("access_token") else "❌ Not logged in"

# ---------------------------
# OAuth Callback
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str):
    tokens = get_tokens(code)
    if "access_token" in tokens:
        SPOTIFY_TOKENS["access_token"] = tokens["access_token"]
        profile = get_user_profile(tokens["access_token"])
        if profile:
            SPOTIFY_TOKENS["user_id"] = profile["id"]
        return """<script>window.close(); alert('Spotify authentication successful!');</script>"""
    return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}

# ---------------------------
# JSON Parsing Helper
# ---------------------------
def parse_uploaded_files(files):
    """
    Reads all uploaded JSON files and extracts:
    - track_uri
    - artist_uri
    - album_uri
    - artist_name
    - album_name
    - ms_played
    """
    if not files:
        return []

    records = []

    for f in files:
        if hasattr(f, "read"):
            data = json.loads(f.read().decode("utf-8"))
        else:
            data = json.loads(f.decode("utf-8"))

        entries = data["tracks"] if isinstance(data, dict) and "tracks" in data else data

        for t in entries:
            records.append({
                "track_uri": t.get("spotify_track_uri"),
                "artist_uri": t.get("spotify_artist_uri"),
                "album_uri": t.get("spotify_album_uri"),
                "artist_name": t.get("artist_name"),
                "album_name": t.get("album_name"),
                "ms_played": t.get("ms_played", 0)
            })

    return records

# ---------------------------
# Spotify Image Fetch
# ---------------------------
def fetch_spotify_image(entity_uri, entity_type, token):
    """
    entity_type ∈ {"artist", "album"}
    """
    if entity_uri is None:
        return None

    entity_id = entity_uri.split(":")[-1]
    url = f"https://api.spotify.com/v1/{entity_type}s/{entity_id}"

    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return None

    data = resp.json()
    images = data.get("images", [])
    if images:
        return images[0]["url"]
    return None

# ---------------------------
# Playlist Generator
# ---------------------------
def generate_playlist(files):
    access_token = SPOTIFY_TOKENS.get("access_token")
    user_id = SPOTIFY_TOKENS.get("user_id")

    if not access_token or not user_id:
        return "❌ Please login first.", None

    records = parse_uploaded_files(files)
    if not records:
        return "❌ No valid tracks.", None

    # Remove duplicates and keep highest ms_played
    unique = {}
    for r in records:
        uri = r["track_uri"]
        if not uri:
            continue
        if uri not in unique or r["ms_played"] > unique[uri]:
            unique[uri] = r["ms_played"]

    # Sort by ms_played descending
    sorted_tracks = sorted(unique.items(), key=lambda x: x[1], reverse=True)

    # Cap at 1000
    capped = [uri for uri, _ in sorted_tracks[:1000]]

    # Create playlist
    playlist_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Generated Playlist", "public": True}
    )
    if playlist_resp.status_code != 201:
        return f"❌ Failed: {playlist_resp.text}", None

    playlist_id = playlist_resp.json()["id"]

    # Upload in batches
    for i in range(0, len(capped), 100):
        batch = capped[i:i+100]
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"uris": batch}
        )
        if add_resp.status_code != 201:
            return f"❌ Add failed: {add_resp.text}", None

    return f"🎉 Playlist created with {len(capped)} tracks!", None

# ---------------------------
# Artist Rankings
# ---------------------------
def get_top_artists(files):
    token = SPOTIFY_TOKENS.get("access_token")
    if not token:
        return "❌ Please login first."

    records = parse_uploaded_files(files)
    if not records:
        return "❌ No data."

    stats = {}

    for r in records:
        artist = r["artist_name"]
        uri = r["artist_uri"]
        ms = r["ms_played"]

        if not artist:
            continue

        if artist not in stats:
            stats[artist] = {"uri": uri, "ms": 0, "img": None}

        stats[artist]["ms"] += ms

    # Fetch images
    for artist, info in stats.items():
        info["img"] = fetch_spotify_image(info["uri"], "artist", token)

    # Sort
    top = sorted(stats.items(), key=lambda x: x[1]["ms"], reverse=True)[:50]

    html = "<h2>Your Top 50 Artists</h2>"
    for name, info in top:
        hours = round(info["ms"] / 3600000, 2)
        img = info["img"] or ""
        html += f"""
        <div style='display:flex;align-items:center;margin:10px 0;'>
            <img src="{img}" style="width:80px;height:80px;border-radius:50%;margin-right:15px;">
            <div>
                <b>{name}</b><br>
                {hours} hours listened
            </div>
        </div>
        """
    return html

# ---------------------------
# Album Rankings
# ---------------------------
def get_top_albums(files):
    token = SPOTIFY_TOKENS.get("access_token")
    if not token:
        return "❌ Please login first."

    records = parse_uploaded_files(files)
    if not records:
        return "❌ No data."

    stats = {}

    for r in records:
        album = r["album_name"]
        uri = r["album_uri"]
        ms = r["ms_played"]

        if not album:
            continue

        if album not in stats:
            stats[album] = {"uri": uri, "ms": 0, "img": None}

        stats[album]["ms"] += ms

    for album, info in stats.items():
        info["img"] = fetch_spotify_image(info["uri"], "album", token)

    top = sorted(stats.items(), key=lambda x: x[1]["ms"], reverse=True)[:50]

    html = "<h2>Your Top 50 Albums</h2>"
    for name, info in top:
        hours = round(info["ms"] / 3600000, 2)
        img = info["img"] or ""
        html += f"""
        <div style='display:flex;align-items:center;margin:10px 0;'>
            <img src="{img}" style="width:80px;height:80px;border-radius:10px;margin-right:15px;">
            <div>
                <b>{name}</b><br>
                {hours} hours played
            </div>
        </div>
        """
    return html

# ---------------------------
# Gradio App
# ---------------------------
# ---------------------------
# Gradio App
# ---------------------------
with gr.Blocks(title="Spotify Extended App") as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist & Stats Dashboard")

    with gr.Tabs():
        with gr.Tab("Playlist Generator"):
            login_btn = gr.Button("Login with Spotify")
            status_box = gr.Textbox(value=check_login_status(), interactive=False)
            status_btn = gr.Button("Refresh")
            status_btn.click(check_login_status, [], status_box)

            auth_url = get_auth_url()
            login_btn.click(None, None, None, js=f"window.open('{auth_url}', '_blank')")

            files = gr.File(file_types=[".json"], file_count="multiple")
            submit_btn = gr.Button("Generate Playlist")
            output_text = gr.Textbox()
            submit_btn.click(generate_playlist, files, output_text)

        with gr.Tab("Top Artists"):
            artist_files = gr.File(file_types=[".json"], file_count="multiple")
            artist_btn = gr.Button("Show Top 50 Artists")
            artist_html = gr.HTML()
            artist_btn.click(get_top_artists, artist_files, artist_html)

        with gr.Tab("Top Albums"):
            album_files = gr.File(file_types=[".json"], file_count="multiple")
            album_btn = gr.Button("Show Top 50 Albums")
            album_html = gr.HTML()
            album_btn.click(get_top_albums, album_files, album_html)

app = gr.mount_gradio_app(app, gradio_app, path="/")

