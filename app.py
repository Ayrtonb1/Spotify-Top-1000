import os
import json
import base64
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import gradio as gr
import uuid

# ---------------------------
# Spotify Credentials
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://spotify-top-1000.onrender.com/spotify/callback")

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI()

# ---------------------------
# In-memory session store
# ---------------------------
session_tokens = {}  # state -> access_token

# ---------------------------
# Spotify Helpers
# ---------------------------
def get_auth_url(state: str):
    scopes = "playlist-modify-public playlist-modify-private user-library-read"
    return (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scopes}"
        f"&state={state}"
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
# OAuth Callback Endpoint
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(request: Request, code: str, state: str):
    tokens = get_tokens(code)
    if "access_token" not in tokens:
        return HTMLResponse(f"<h2>Spotify auth failed</h2><pre>{tokens}</pre>")
    session_tokens[state] = tokens["access_token"]
    return HTMLResponse(f"<h2>Authentication successful!</h2><p>You can now return to the app to upload files and generate your playlist.</p>")

# ---------------------------
# Playlist Generator Logic
# ---------------------------
def generate_playlist(state: str, files):
    access_token = session_tokens.get(state)
    if not access_token:
        return "❌ Please login first.", None
    if not files:
        return "❌ No files uploaded.", None

    # Ensure files are bytes
    if not isinstance(files, list):
        files = [files]
    all_tracks = []
    for f in files:
        try:
            data = json.loads(f.read().decode("utf-8") if hasattr(f, "read") else f.decode("utf-8"))
            tracks = data.get("tracks", [])
            all_tracks.extend(tracks)
        except Exception as e:
            return f"❌ Error reading file: {e}", None
    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    # Playlist creation (example)
    playlist_name = "Generated Playlist"
    playlist_description = "Made automatically"
    # You can call Spotify API here to create the playlist using access_token

    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None

# ---------------------------
# Gradio UI
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:
    gr.Markdown("## 🎵 Spotify Playlist Generator")
    gr.Markdown("Follow the steps below to login, upload files, and generate a playlist.")

    state = str(uuid.uuid4())  # unique state for this session

    # Step 1: Login
    gr.Markdown(f"### Step 1: Login to Spotify")
    login_btn = gr.Button("Login with Spotify", elem_classes="primary-btn")
    login_btn.click(
        fn=lambda: None,
        inputs=[],
        outputs=[],
        js=f'() => window.open("{get_auth_url(state)}", "_blank")'
    )

    # Step 2: Upload
    gr.Markdown("### Step 2: Upload JSON Files")
    files = gr.File(label="Upload JSON Files", file_types=[".json"], file_count="multiple", type="binary")

    # Step 3: Generate
    gr.Markdown("### Step 3: Generate Playlist")
    output_text = gr.Textbox(label="Status")
    output_img = gr.Image(label="Preview (optional)", visible=False)
    submit = gr.Button("Generate Playlist")
    submit.click(fn=generate_playlist, inputs=[gr.State(value=state), files], outputs=[output_text, output_img])

# Mount Gradio to FastAPI
app = gr.mount_gradio_app(app, gradio_app, path="/")
