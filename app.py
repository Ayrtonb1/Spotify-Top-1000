import os
import json
from collections import Counter
from urllib.parse import urlencode

import gradio as gr
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ================================================================
# CONFIG
# ================================================================

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")

SPACE_URL = "https://Ayrtonb1-spotify-top-1000.hf.space"
REDIRECT_URI = f"{SPACE_URL}/"   # No route needed

PLAYLIST_NAME = "Best 1000 All-Time Tracks"
SCOPE = (
    "user-top-read user-library-read user-read-recently-played "
    "playlist-modify-private playlist-modify-public"
)

# ================================================================
# HELPERS
# ================================================================

def get_spotify_login_url():
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def extract_code_from_url(url):
    """Extract the authorization code from Spotify redirect URL"""
    try:
        qs = url.split("?", 1)[1]
        params = dict(param.split("=") for param in qs.split("&"))
        return params.get("code")
    except Exception:
        return None


# ================================================================
# PLAYLIST GENERATOR
# ================================================================

def generate_playlist(auth_code, files):
    if not auth_code:
        return "❌ Please authenticate first.", None

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

        # Load all JSON files
        all_tracks = []
        for f in files:
            if isinstance(f, bytes):
                all_tracks.extend(json.loads(f.decode("utf-8")))
            else:
                all_tracks.extend(json.load(f))
        logs.append(f"📂 Loaded {len(all_tracks):,} plays from {len(files)} files.")

        # Aggregate playtime
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

        # Match Spotify track IDs
        matched_ids = []
        for t in top_tracks:
            if t.startswith("spotify:track:"):
                matched_ids.append(t.split(":")[-1])
                continue
            try:
                name, artist = t.split(" - ", 1) if " - " in t else (t, "")
                results = sp.search(f"track:{name} artist:{artist}", type="track", limit=1)
                items = results["tracks"]["items"]
                if items:
                    matched_ids.append(items[0]["id"])
            except:
                pass

        # Create playlist
        playlist = sp.user_playlist_create(
            user["id"],
            PLAYLIST_NAME,
            public=False,
            description="Top 1000 songs ranked by total playtime.",
        )
        for i in range(0, len(matched_ids), 100):
            sp.playlist_add_items(playlist["id"], matched_ids[i:i+100])

        playlist_url = playlist["external_urls"]["spotify"]
        logs.append(f"🎉 Playlist created: {playlist_url}")

        return "\n".join(logs), f"<a href='{playlist_url}' target='_blank'>{playlist_url}</a>"

    except Exception as e:
        return f"❌ Error: {e}", None


# ================================================================
# GRADIO UI - Sleek, 3-Step Workflow
# ================================================================

with gr.Blocks(title="Spotify Top 1000 Playlist Builder") as demo:
    gr.Markdown("<h1 style='text-align:center'>🎧 Spotify Playlist Builder</h1>", elem_id="title")

    # ---------------- Step 1: Login ----------------
    with gr.Row():
        with gr.Column(scale=1, min_width=200):
            login_btn = gr.Button("🔐 Login with Spotify", variant="primary")
        with gr.Column(scale=2, min_width=400):
            login_status = gr.HTML("<i>Not logged in</i>")

    auth_code_state = gr.State(None)

    def login_spotify():
        login_url = get_spotify_login_url()
        return f"<a href='{login_url}' target='_blank'>Click here to authenticate with Spotify</a>"

    login_btn.click(login_spotify, outputs=login_status)

    # ---------------- Step 2: Upload JSON ----------------
    with gr.Row():
        files = gr.File(file_count="multiple", file_types=[".json"], type="binary", label="Upload your Streaming History JSON files")

    # ---------------- Step 3: Generate Playlist ----------------
    with gr.Row():
        run_btn = gr.Button("🎶 Generate Playlist", variant="primary")
    with gr.Row():
        logs = gr.Textbox(lines=20, label="Logs")
        link = gr.HTML(label="Playlist Link")

    run_btn.click(generate_playlist, inputs=[auth_code_state, files], outputs=[logs, link])

# ================================================================
# LAUNCH
# ================================================================
if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
