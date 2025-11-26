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

def get_user_id(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get("https://api.spotify.com/v1/me", headers=headers)
    if resp.status_code == 200:
        return resp.json()["id"]
    return None

def create_playlist(access_token, user_id, name="Generated Playlist", description="Created via app"):
    url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"name": name, "description": description, "public": True}
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code == 201:
        return resp.json()["id"]
    return None

def add_tracks_to_playlist(access_token, playlist_id, track_uris):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    for i in range(0, len(track_uris), 100):
        chunk = track_uris[i:i+100]
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        data = {"uris": chunk}
        resp = requests.post(url, headers=headers, json=data)
        if resp.status_code not in [201, 200]:
            return False
    return True

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
        window.close();
        alert('Spotify authentication successful!');
        </script>"""
    return {"error": "Failed to authenticate with Spotify.", "tokens": tokens}

# ---------------------------
# Playlist Generation
# ---------------------------
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
            if isinstance(data, dict) and "tracks" in data:
                tracks = data["tracks"]
            elif isinstance(data, list):
                tracks = data
            else:
                tracks = []
            all_tracks.extend(tracks)
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    # Cap playlist at 1000
    capped_tracks = all_tracks[:1000]

    # Expect track URIs in JSON under "uri"
    track_uris = [t["uri"] for t in capped_tracks if "uri" in t]
    if not track_uris:
        return "❌ No valid Spotify track URIs found in files.", None

    user_id = get_user_id(access_token)
    if not user_id:
        return "❌ Failed to get Spotify user ID.", None

    playlist_id = create_playlist(access_token, user_id, name="Generated Playlist")
    if not playlist_id:
        return "❌ Failed to create playlist on Spotify.", None

    success = add_tracks_to_playlist(access_token, playlist_id, track_uris)
    if not success:
        return "❌ Failed to add tracks to playlist.", None

    return f"✅ Playlist created with {len(track_uris)} tracks!", None

# ---------------------------
# Gradio Interface
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:
    gr.Markdown("# 🎵 Spotify Playlist Generator")
    gr.Markdown("## Step 1: Login to Spotify")

    login_btn = gr.Button(
        "Login with Spotify",
        elem_classes="spotify-login-btn"
    )
    status_box = gr.Textbox(value=check_login_status(), interactive=False, label="Login Status")
    status_btn = gr.Button("🔄 Check Login Status")
    status_btn.click(fn=check_login_status, inputs=[], outputs=[status_box])

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

# Add Spotify button style
gradio_app.load(js="""
const style = document.createElement('style');
style.innerHTML = `
.spotify-login-btn {
    background-color: #1DB954 !important;
    color: white !important;
    font-weight: bold !important;
    border-radius: 25px !important;
    padding: 12px 20px !important;
    font-size: 16px !important;
    text-transform: uppercase !important;
    cursor: pointer !important;
}
.spotify-login-btn:hover {
    background-color: #1ed760 !important;
}
`;
document.head.appendChild(style);
""")

# ---------------------------
# Mount Gradio on FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
