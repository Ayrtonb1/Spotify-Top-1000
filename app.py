import os
import json
import base64
import requests
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
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

    # Show access token in browser
    return {
        "message": "Authentication successful! Copy this access token into the Gradio UI.",
        "access_token": tokens["access_token"],
    }


# ---------------------------
# 🎧 Playlist Generator Logic
# ---------------------------
def generate_playlist(session_token, files):

    # Ensure files is ALWAYS a list of bytes
    if files is None:
        files = []
    elif not isinstance(files, list):
        files = [files]

    normalized_files = []
    for f in files:
        if hasattr(f, "read"):
            normalized_files.append(f.read())
        elif isinstance(f, bytes):
            normalized_files.append(f)

    files = normalized_files

    if not session_token:
        return "❌ Please authenticate first.", None

    if not files:
        return "❌ No files uploaded.", None

    # Combine all JSON from uploaded files
    all_tracks = []
    for file_bytes in files:
        try:
            data = json.loads(file_bytes.decode("utf-8"))
            tracks = data.get("tracks", [])
            all_tracks.extend(tracks)
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    # Create playlist logic (example)
    playlist_name = "Generated Playlist"
    playlist_description = "Made automatically"

    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None


# ---------------------------
# 🎨 Gradio UI
# ---------------------------
with gr.Blocks(title="Playlist Generator") as gradio_app:

    gr.Markdown("# 🎵 Spotify Playlist Generator")
    gr.Markdown("Authenticate, then upload your JSON files.")

    auth_url = get_auth_url()
    gr.Markdown(f"### 🔗 [Click here to authenticate with Spotify]({auth_url})")

    session_token = gr.Textbox(label="Paste Access Token", type="password")

    files = gr.File(
        label="Upload JSON Files",
        file_types=[".json"],
        file_count="multiple",
        type="binary"   # ensures bytes input
    )

    output_text = gr.Textbox(label="Status")
    output_img = gr.Image(label="Preview (optional)", visible=False)

    submit = gr.Button("Generate Playlist")

    submit.click(
        fn=generate_playlist,
        inputs=[session_token, files],
        outputs=[output_text, output_img]
    )


# ---------------------------
# 🔌 Mount Gradio onto FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")


# ---------------------------
# ✔ Done
# ---------------------------
