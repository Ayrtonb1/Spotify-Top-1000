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
SPOTIFY_TOKENS = {"access_token": None}

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
        # Close popup automatically
        return """<script>
        alert('Spotify authentication successful!');
        window.close();
        </script>"""
    else:
        return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}

# ---------------------------
# Playlist Generation
# ---------------------------
def extract_uris(data):
    """Recursively extract all 'spotify_track_uri' values from JSON."""
    uris = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "spotify_track_uri" and isinstance(v, str):
                uris.append(v)
            else:
                uris.extend(extract_uris(v))
    elif isinstance(data, list):
        for item in data:
            uris.extend(extract_uris(item))
    return uris

def generate_playlist(files):
    access_token = SPOTIFY_TOKENS.get("access_token")
    if not access_token:
        return "❌ Please login to Spotify first.", None
    if not files:
        return "❌ No files uploaded.", None

    # Normalize files
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
            all_tracks.extend(data if isinstance(data, list) else [data])
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    # Extract Spotify URIs
    track_uris = extract_uris(all_tracks)
    if not track_uris:
        return "❌ No valid Spotify track URIs found in files.", None

    # Cap playlist at 1000
    track_uris = track_uris[:1000]

    # Placeholder for creating playlist in Spotify
    playlist_name = "Generated Playlist"
    return f"🎉 Playlist generated with {len(track_uris)} tracks!", None

# ---------------------------
# Gradio Interface
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist Generator")
    gr.Markdown("## Step 1: Login to Spotify")

    login_btn = gr.Button("🔑 Login to Spotify")
    status_box = gr.Textbox(value=check_login_status(), interactive=False, label="Login Status")
    status_btn = gr.Button("🔄 Check Login Status")
    status_btn.click(fn=check_login_status, inputs=[], outputs=[status_box])

    # Open Spotify auth in popup
    auth_url = get_auth_url()
    login_btn.click(fn=lambda: None, inputs=[], outputs=[], js=f"window.open('{auth_url}', '_blank')")

    gr.Markdown("## Step 2: Upload your JSON files")
    files = gr.File(
        label="Upload JSON Files",
        file_types=[".json"],
        file_count="multiple",
        type="binary"
    )

    gr.Markdown("## Step 3: Generate Playlist")
    submit_btn = gr.Button("🎶 Generate Playlist")
    output_text = gr.Textbox(label="Status")
    output_img = gr.Image(label="Preview", visible=False)

    submit_btn.click(fn=generate_playlist, inputs=[files], outputs=[output_text, output_img])

# ---------------------------
# Mount Gradio on FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
