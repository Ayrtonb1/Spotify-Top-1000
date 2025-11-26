import os
import json
import requests
import gradio as gr
from fastapi import FastAPI

# ---------------------------
# 🔐 Spotify Credentials
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

# ---------------------------
# 🌐 FastAPI app
# ---------------------------
app = FastAPI()

# ---------------------------
# 🎵 Spotify Helpers
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

# ---------------------------
# 🔙 OAuth Callback
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str):
    tokens = get_tokens(code)
    if "access_token" not in tokens:
        return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}

    return {
        "message": "Authentication successful! Copy this access token below.",
        "access_token": tokens["access_token"],
    }

# ---------------------------
# 🎧 Playlist Generator
# ---------------------------
def generate_playlist(session_token, files):
    if not session_token:
        return "❌ Please authenticate first.", None
    if not files:
        return "❌ No files uploaded.", None

    # Normalize files to list of bytes
    if not isinstance(files, list):
        files = [files]
    all_tracks = []

    for f in files:
        try:
            data = json.load(f) if hasattr(f, "read") else json.loads(f.decode("utf-8"))
            tracks = data.get("tracks", [])
            all_tracks.extend(tracks)
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    # Example playlist creation
    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None

# ---------------------------
# 🎨 Gradio UI (v5.x)
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:

    # Custom style
    gr.HTML("""
    <style>
    body { background-color: #121212; color: #fff; font-family: Arial, sans-serif; }
    .gr-button { background-color: #1DB954; color: #fff; font-weight: bold; border-radius: 8px; }
    .gr-textbox input { background-color: #1e1e1e; color: #fff; border-radius: 5px; }
    .gr-file input { color: #fff; }
    .gr-markdown { color: #fff; }
    </style>
    """)

    gr.Markdown("## 🎵 Spotify Playlist Generator")
    gr.Markdown("Follow the steps below to quickly generate a playlist from JSON files.")

    # Step 1: Authenticate
    auth_url = get_auth_url()
    gr.Markdown(f"### 🔗 [Log in to Spotify]({auth_url})")
    session_token = gr.Textbox(label="Paste Access Token Here", type="password")

    # Step 2: Upload files
    files = gr.File(
        label="Upload JSON Files",
        file_types=[".json"],
        file_count="multiple",
        type="file"
    )

    # Step 3: Generate playlist
    output_text = gr.Textbox(label="Status")
    submit = gr.Button("Generate Playlist")
    submit.click(
        fn=generate_playlist,
        inputs=[session_token, files],
        outputs=[output_text,]
    )

# ---------------------------
# 🔌 Mount Gradio on FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
