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
# Spotify Helpers
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
        # Close popup automatically
        return """<script>
        window.close();
        alert('Spotify authentication successful!');
        </script>"""
    else:
        return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}

# ---------------------------
# Playlist Generation
# ---------------------------
def generate_playlist(files):
    access_token = SPOTIFY_TOKENS.get("access_token")
    user_id = SPOTIFY_TOKENS.get("user_id")
    if not access_token or not user_id:
        return "❌ Please login to Spotify first.", None
    if not files:
        return "❌ No files uploaded.", None

    normalized_files = []
    for f in files:
        if hasattr(f, "read"):
            normalized_files.append(f.read())
        elif isinstance(f, bytes):
            normalized_files.append(f)

    all_tracks = []
    for file_bytes in normalized_files:
        try:
            data = json.loads(file_bytes.decode("utf-8"))
            if isinstance(data, dict) and "tracks" in data:
                tracks = data["tracks"]
            elif isinstance(data, list):
                tracks = data
            else:
                tracks = []
            for t in tracks:
                uri = t.get("spotify_track_uri")
                ms_played = t.get("ms_played", 0)
                if uri:
                    all_tracks.append((uri, ms_played))
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No valid Spotify track URIs found in files.", None

    # Remove duplicates and keep highest playtime
    unique_tracks = {}
    for uri, ms_played in all_tracks:
        if uri not in unique_tracks or ms_played > unique_tracks[uri]:
            unique_tracks[uri] = ms_played

    sorted_tracks = sorted(unique_tracks.items(), key=lambda x: x[1], reverse=True)
    capped_tracks = [uri for uri, _ in sorted_tracks[:1000]]

    playlist_name = "Generated Playlist"
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": playlist_name, "description": "Generated automatically", "public": True}
    )
    if create_resp.status_code != 201:
        return f"❌ Failed to create playlist: {create_resp.text}", None

    playlist_id = create_resp.json()["id"]

    chunk_size = 100
    for i in range(0, len(capped_tracks), chunk_size):
        chunk = capped_tracks[i:i+chunk_size]
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"uris": chunk}
        )
        if add_resp.status_code != 201:
            return f"❌ Failed to add tracks: {add_resp.text}", None

    return f"🎉 Playlist created in your Spotify account with {len(capped_tracks)} unique tracks!", None

# ---------------------------
# Gradio Interface — Spotify-style Dark + Animations
# ---------------------------
with gr.Blocks(title="Spotify Top 1000 Playlist") as gradio_app:
    gr.HTML("""
    <style>
        /* Dark theme background */
        body, .gradio-container { background-color: #121212 !important; color: #fff !important; font-family: 'Spotify Circular', sans-serif; }

        /* Panel styling */
        .gr-panel { background-color: #1e1e1e !important; border-radius: 16px !important; padding: 20px !important; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }

        /* Spotify green buttons */
        .gr-button { background-color: #1DB954 !important; color: white !important; font-weight: bold; border-radius: 24px !important; padding: 12px 24px; transition: transform 0.2s, box-shadow 0.2s; }
        .gr-button:hover { transform: scale(1.05); box-shadow: 0 0 20px #1DB954; }

        /* Textbox and file input */
        .gr-textbox, .gr-file { background-color: #2a2a2a !important; color: white !important; border: 1px solid #444 !important; border-radius: 8px !important; }

        /* Animated header */
        h1, h2, h3 { transition: color 0.3s; }
        h1:hover { color: #1DB954; }

        /* Cursor tracer */
        .cursor-dot { position: fixed; top: 0; left: 0; width: 12px; height: 12px; border-radius: 50%; background: #1DB954; pointer-events: none; z-index: 9999; mix-blend-mode: difference; transition: transform 0.05s ease-out; }
    </style>
    <div class="cursor-dot" id="cursor-dot"></div>
    <script>
        const dot = document.getElementById('cursor-dot');
        document.addEventListener('mousemove', e => {
            dot.style.transform = `translate(${e.clientX - 6}px, ${e.clientY - 6}px)`;
        });
    </script>
    """)

    gr.Markdown("# 🎵 Spotify Top 1000 Playlist Generator")

    gr.Markdown("## Step 1: Login to Spotify")
    login_btn = gr.Button("Login with Spotify")
    status_box = gr.Textbox(value=check_login_status(), interactive=False, label="Login Status")
    status_btn = gr.Button("🔄 Refresh Status")
    status_btn.click(fn=check_login_status, inputs=[], outputs=[status_box])

    auth_url = get_auth_url()
    login_btn.click(fn=lambda: None, inputs=[], outputs=[], js=f"window.open('{auth_url}', '_blank')")

    gr.Markdown("## Step 2: Upload your JSON files")
    files = gr.File(label="Upload JSON Files", file_types=[".json"], file_count="multiple", type="binary")

    gr.Markdown("## Step 3: Generate Playlist")
    submit_btn = gr.Button("🎶 Generate Playlist")
    output_text = gr.Textbox(label="Status")
    output_img = gr.Image(label="Preview", visible=False)

    submit_btn.click(fn=generate_playlist, inputs=[files], outputs=[output_text, output_img])

# ---------------------------
# Mount Gradio on FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
