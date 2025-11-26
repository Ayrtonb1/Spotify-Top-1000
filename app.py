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

# In-memory access token
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
        return """
        <script>
            alert('Spotify authentication successful!');
            window.close();
        </script>
        """
    return {"error": "Authentication failed.", "tokens": tokens}

# ---------------------------
# Playlist Generation
# ---------------------------
def generate_playlist(files):
    access_token = SPOTIFY_TOKENS.get("access_token")
    if not access_token:
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
                all_tracks.extend(data["tracks"])
            elif isinstance(data, list):
                all_tracks.extend(data)
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    capped_tracks = all_tracks[:1000]

    return f"🎉 Playlist generated with {len(capped_tracks)} tracks!", None

# ---------------------------
# Custom CSS for Sleek UI
# ---------------------------
CUSTOM_CSS = """
#login-button {
    background: linear-gradient(90deg, #1DB954, #1ed760);
    color: white;
    font-weight: bold;
    border-radius: 12px;
    transition: 0.3s ease;
}
#login-button:hover {
    transform: scale(1.05);
    box-shadow: 0 0 12px rgba(29,185,84,0.6);
}

.status-box {
    font-weight: bold;
    border-radius: 10px;
    padding: 8px;
    animation: fadeIn 0.6s ease;
}
.status-box:disabled {
    opacity: 1 !important;
}

.filebox {
    border: 2px dashed #888 !important;
    border-radius: 12px !important;
    animation: fadeIn 0.6s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(5px); }
    to { opacity: 1; transform: translateY(0); }
}
"""

# ---------------------------
# Gradio Interface
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator", css=CUSTOM_CSS) as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist Generator")
    gr.Markdown("A modern tool to merge & upload your Spotify tracks.")

    gr.Markdown("---")
    gr.Markdown("## 🔑 Step 1: Login to Spotify")

    login_btn = gr.Button("Login to Spotify", elem_id="login-button")
    status_box = gr.Textbox(value=check_login_status(), interactive=False, label="Login Status", elem_classes="status-box")

    status_btn = gr.Button("🔄 Refresh Login Status")
    status_btn.click(check_login_status, outputs=[status_box])

    auth_url = get_auth_url()
    login_btn.click(fn=lambda: None, inputs=[], outputs=[], js=f"window.open('{auth_url}', '_blank')")

    gr.Markdown("---")
    gr.Markdown("## 📁 Step 2: Upload your JSON files")

    files = gr.File(
        label="Upload JSON Files",
        file_types=[".json"],
        file_count="multiple",
        type="binary",
        elem_classes="filebox"
    )

    gr.Markdown("---")
    gr.Markdown("## 🎶 Step 3: Generate Playlist")

    submit_btn = gr.Button("Generate Playlist 🎧")
    output_text = gr.Textbox(label="Status", lines=2)
    output_img = gr.Image(label="Preview", visible=False)

    submit_btn.click(generate_playlist, inputs=[files], outputs=[output_text, output_img])

# ---------------------------
# Mount Gradio
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
