import os
import json
import requests
from fastapi import FastAPI
import gradio as gr

# ---------------------------
# 🔐 Spotify Credentials
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

# Global token storage
SPOTIFY_TOKENS = {}

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
# 🔙 OAuth Callback Endpoint
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str):
    tokens = get_tokens(code)
    if "access_token" not in tokens:
        return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}
    SPOTIFY_TOKENS.update(tokens)
    return {
        "message": "Authentication successful! You can now return to the web app.",
    }

# ---------------------------
# 🎧 Playlist Generator Logic
# ---------------------------
def generate_playlist(files):
    if not SPOTIFY_TOKENS.get("access_token"):
        return "❌ Please log in first.", None

    if not files:
        return "❌ No files uploaded.", None

    all_tracks = []
    for file_bytes in files:
        try:
            data = json.loads(file_bytes.decode("utf-8"))
            if isinstance(data, dict) and "tracks" in data:
                all_tracks.extend(data["tracks"])
            elif isinstance(data, list):
                all_tracks.extend(data)
            else:
                return f"❌ Unexpected JSON format.", None
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    # Cap playlist at 1000 tracks
    all_tracks = all_tracks[:1000]

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None

# ---------------------------
# 🎨 Gradio UI
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:
    gr.Markdown("## 🎵 Spotify Playlist Generator")
    gr.Markdown("Follow the 3 simple steps below:")

    # --- Step 1: Login ---
    with gr.Group():
        gr.Markdown("### Step 1: Log in to Spotify")
        login_btn = gr.Button("🔑 Login to Spotify", elem_id="login-btn")
        auth_status = gr.Textbox(value="❌ Not logged in", interactive=False, elem_id="auth-status")

    auth_url = get_auth_url()
    login_btn.click(
        fn=lambda: None,
        inputs=[],
        outputs=[],
        js=f"window.open('{auth_url}', '_blank');"
    )

    def check_login():
        return "✅ Logged in!" if SPOTIFY_TOKENS.get("access_token") else "❌ Not logged in"
    
    gr.Timer(interval=2, fn=check_login, outputs=[auth_status])

    # --- Step 2: Upload ---
    with gr.Group():
        gr.Markdown("### Step 2: Upload JSON Files")
        files = gr.File(
            label="Upload JSON Files",
            file_types=[".json"],
            file_count="multiple",
            type="binary"  # bytes input
        )

    # --- Step 3: Generate Playlist ---
    with gr.Group():
        gr.Markdown("### Step 3: Generate Playlist")
        output_text = gr.Textbox(label="Status", interactive=False)
        generate_btn = gr.Button("🎶 Generate Playlist")

    generate_btn.click(
        fn=generate_playlist,
        inputs=[files],
        outputs=[output_text]
    )

# ---------------------------
# 🔌 Mount Gradio onto FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
