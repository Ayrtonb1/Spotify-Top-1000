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
        # Close popup automatically and notify user
        return """<script>
        alert('Spotify authentication successful!');
        window.close();
        </script>"""
    else:
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

    # Filter tracks with valid Spotify URIs
    valid_tracks = [t for t in all_tracks if t.get("spotify_track_uri")]
    if not valid_tracks:
        return "❌ No valid Spotify track URIs found in files.", None

    # Sort by playtime (ms_played) descending
    valid_tracks.sort(key=lambda x: x.get("ms_played", 0), reverse=True)

    # Cap at 1000 tracks
    top_uris = [t["spotify_track_uri"] for t in valid_tracks[:1000]]

    # Create playlist in user's Spotify account
    user_resp = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if user_resp.status_code != 200:
        return f"❌ Failed to get Spotify user info: {user_resp.json()}", None
    user_id = user_resp.json()["id"]

    playlist_data = {
        "name": "Top 1000 Generated Playlist",
        "description": "Generated from your listening history (weighted by playtime)",
        "public": True,
    }
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=playlist_data,
    )
    if create_resp.status_code != 201:
        return f"❌ Failed to create playlist: {create_resp.json()}", None

    playlist_id = create_resp.json()["id"]

    # Add tracks in batches of 100 (Spotify API limit)
    for i in range(0, len(top_uris), 100):
        batch = top_uris[i:i + 100]
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"uris": batch},
        )
        if add_resp.status_code != 201:
            return f"❌ Failed to add tracks: {add_resp.json()}", None

    return f"🎉 Playlist created with {len(top_uris)} tracks!", None

# ---------------------------
# Gradio Interface
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist Generator")
    gr.Markdown("## Step 1: Login to Spotify")

    # Styled Spotify login button
    login_btn = gr.Button(
        "🔑 Login with Spotify",
        elem_classes="spotify-login-btn"
    )
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
# Add custom CSS for Spotify login button
# ---------------------------
gradio_app.load(
    fn=lambda: None,
    inputs=[],
    outputs=[],
    _css="""
    .spotify-login-btn button {
        background-color: #1DB954 !important;
        color: white !important;
        font-weight: bold !important;
        font-size: 16px !important;
        border-radius: 24px !important;
        padding: 12px 24px !important;
    }
    .spotify-login-btn button:hover {
        background-color: #1ed760 !important;
    }
    """
)

# ---------------------------
# Mount Gradio on FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
