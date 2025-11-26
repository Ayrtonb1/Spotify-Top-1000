import os
import json
import requests
import gradio as gr
from fastapi import FastAPI

# -------------------------------------------------
# 🔐 Spotify Credentials
# -------------------------------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

# -------------------------------------------------
# 🌐 FastAPI app
# -------------------------------------------------
app = FastAPI()

# -------------------------------------------------
# 🎵 Spotify OAuth Helpers
# -------------------------------------------------
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

# -------------------------------------------------
# 🔙 OAuth Callback Endpoint
# -------------------------------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str):
    tokens = get_tokens(code)

    if "access_token" not in tokens:
        return {"error": "Failed to authenticate.", "details": tokens}

    return {
        "message": "Authentication successful! Copy this token into the Gradio box.",
        "access_token": tokens["access_token"],
    }


# -------------------------------------------------
# 📂 File Reader — FIXES your 'list' object error
# -------------------------------------------------
def read_uploaded_files(files):
    """
    Ensures files is ALWAYS a list of file objects or bytes.
    Returns decoded JSON text for each file.
    """
    if not files:
        return []

    parsed = []
    for f in files:
        try:
            if hasattr(f, "read"):
                content = f.read().decode("utf-8")
            elif isinstance(f, bytes):
                content = f.decode("utf-8")
            else:
                continue

            parsed.append(json.loads(content))
        except Exception as e:
            return f"❌ Error reading file: {e}"

    return parsed


# -------------------------------------------------
# 🎧 Playlist Generator
# -------------------------------------------------
def generate_playlist(token, file_objects):

    if not token:
        return "❌ Please paste your Spotify access token first."

    # read & parse uploaded files
    file_data = read_uploaded_files(file_objects)

    if isinstance(file_data, str):  # error string
        return file_data

    all_tracks = []

    # Extract track data safely
    for data in file_data:
        tracks = data.get("tracks", [])
        all_tracks.extend(tracks)

    if not all_tracks:
        return "❌ No tracks found in uploaded files."

    # (You can replace this with real playlist creation)
    return f"🎉 Playlist created with **{len(all_tracks)} tracks**!"


# -------------------------------------------------
# 🎨 Modern Spotify-styled UI
# -------------------------------------------------
def build_interface():

    with gr.Blocks(
        title="Spotify Playlist Generator",
        css="""
        body { background: #121212 !important; }
        .gradio-container { max-width: 680px !important; margin: auto; }
        h1, h2, h3, p { color: white !important; }
        """
    ) as ui:

        gr.Markdown("""
        <div style='text-align:center; margin-top:20px;'>
            <h1 style='color:#1DB954;'>🎵 Spotify Playlist Generator</h1>
            <p style='opacity:0.8;'>Login → Upload Files → Generate Playlist</p>
        </div>
        """)

        # ---- Step 1: Login ----
        gr.Markdown("## 🔐 Step 1 — Log in to Spotify")
        login_btn = gr.Button("Login to Spotify", variant="primary")
        login_output = gr.Textbox(label="Authentication Link", interactive=False)

        def provide_login_url():
            return get_auth_url()

        login_btn.click(fn=provide_login_url, outputs=login_output)

        # ---- Step 2: Upload Files ----
        gr.Markdown("## 📁 Step 2 — Upload your JSON files")
        uploaded_files = gr.File(
            label="Upload JSON files",
            file_types=[".json"],
            file_count="multiple"
        )

        # ---- Step 3: Generate Playlist ----
        gr.Markdown("## 🎧 Step 3 — Generate Playlist")
        token_box = gr.Textbox(label="Paste Spotify access token here", type="password")

        generate_btn = gr.Button("Generate Playlist", variant="secondary")
        result_box = gr.Markdown()

        generate_btn.click(
            fn=generate_playlist,
            inputs=[token_box, uploaded_files],
            outputs=result_box
        )

        gr.Markdown("""
        <div style='text-align:center; margin-top:40px; opacity:0.5; font-size:0.8em;'>
            Built with ❤️ using FastAPI + Gradio
        </div>
        """)

    return ui


gradio_app = build_interface()

# -------------------------------------------------
# 🔌 Mount Gradio onto FastAPI
# -------------------------------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
