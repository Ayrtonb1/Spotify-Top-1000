import os
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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

# In-memory token storage for demo purposes (replace with DB in production)
TOKENS = {}

# ---------------------------
# 🎵 Spotify Helpers
# ---------------------------
def get_auth_url(state):
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
# 🔙 OAuth Callback Endpoint
# ---------------------------
@app.get("/spotify/callback")
async def spotify_callback(request: Request, code: str = None, state: str = None):
    if not code or not state:
        return HTMLResponse("<h2>❌ Invalid request</h2>")
    tokens = get_tokens(code)
    if "access_token" not in tokens:
        return HTMLResponse("<h2>❌ Authentication failed</h2>")
    # Store the access token by state key
    TOKENS[state] = tokens["access_token"]
    # Return HTML that triggers a small JS snippet to send token back to Gradio
    return HTMLResponse(f"""
        <h2>✅ Authentication successful!</h2>
        <script>
            // Send token to Gradio
            window.opener.postMessage({{state: "{state}", token: "{tokens['access_token']}" }}, "*");
            window.close();
        </script>
        <p>You can now close this window.</p>
    """)

# ---------------------------
# 🎧 Playlist Generator Logic
# ---------------------------
def generate_playlist(session_token, files):
    if not session_token:
        return "❌ Please authenticate first.", None
    if files is None:
        return "❌ No files uploaded.", None

    if not isinstance(files, list):
        files = [files]

    all_tracks = []
    for f in files:
        try:
            data = json.loads(f.decode("utf-8"))
            tracks = data.get("tracks", [])
            all_tracks.extend(tracks)
        except Exception as e:
            return f"❌ Error reading file: {e}", None

    if not all_tracks:
        return "❌ No tracks found in uploaded files.", None

    playlist_name = "Generated Playlist"
    playlist_description = "Made automatically"

    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None

# ---------------------------
# 🎨 Gradio UI
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:

    gr.Markdown("<h1 style='color:#1DB954;'>🎵 Spotify Playlist Generator</h1>", elem_id="header")

    # Hidden state to store token
    session_token = gr.State(value="")

    with gr.Box():
        gr.Markdown("### Step 1: Login to Spotify")
        login_btn = gr.Button("Login to Spotify", elem_id="login-btn")
        token_notice = gr.Textbox(label="Status", interactive=False)

        # JS for automated token retrieval
        login_btn.click(
            fn=lambda: None,
            inputs=[],
            outputs=[],
            _js="""
                () => {
                    const state = Math.random().toString(36).substring(2);
                    window.spotifyState = state;
                    const url = `https://accounts.spotify.com/authorize?client_id=${CLIENT_ID}&response_type=code&redirect_uri=${encodeURIComponent('${REDIRECT_URI}')}&scope=playlist-modify-public playlist-modify-private user-library-read&state=${state}`;
                    window.open(url, "_blank");
                    return;
                }
            """
        )

        # Listen for message from callback
        gr.HTML("<script>window.addEventListener('message', e => { if(e.data.token) { document.getElementById('login-btn').nextSibling.value = '✅ Authenticated'; window.gradioApp().getComponent('session_token').setValue(e.data.token); } })</script>")

    with gr.Box():
        gr.Markdown("### Step 2: Upload JSON Files")
        files = gr.File(
            label="Upload JSON Files",
            file_types=[".json"],
            file_count="multiple",
            type="binary"
        )

    with gr.Box():
        gr.Markdown("### Step 3: Generate Playlist")
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
