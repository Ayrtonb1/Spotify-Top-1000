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
TOKENS = {}  # in-memory token storage

# ---------------------------
# 🎵 Spotify Helpers
# ---------------------------
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
    TOKENS[state] = tokens["access_token"]
    return HTMLResponse(f"""
        <h2>✅ Authentication successful!</h2>
        <script>
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

    return f"🎉 Playlist generated with {len(all_tracks)} tracks!", None

# ---------------------------
# 🎨 Gradio UI
# ---------------------------
with gr.Blocks(title="Spotify Playlist Generator") as gradio_app:

    # ---- Custom CSS ----
    gr.HTML("""
    <style>
        body { font-family: 'Arial', sans-serif; background-color: #121212; color: #fff; }
        #header { color: #1DB954; font-weight: bold; }
        .step-box { border-radius: 12px; padding: 20px; margin: 10px 0; background: linear-gradient(145deg, #1DB95422, #191414); box-shadow: 0 4px 12px rgba(0,0,0,0.3);}
        button { background-color: #1DB954; color: white; border:none; padding:12px 20px; border-radius:8px; cursor:pointer; transition: all 0.3s ease; font-weight:bold; }
        button:hover { background-color:#1ed760; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.5);}
        input, textarea { border-radius:8px; padding:8px; border:none; width:100%; margin-top:5px;}
        .gr-file { color:#1DB954; font-weight:bold; }
        h2 { color:#1DB954; }
    </style>
    """)

    gr.Markdown("<h1 id='header'>🎵 Spotify Playlist Generator</h1>")

    # ---- Step 1: Login ----
    with gr.Box(elem_classes="step-box"):
        gr.Markdown("### Step 1: Login to Spotify")
        session_token = gr.State(value="")
        login_btn = gr.Button("Login to Spotify")
        status_box = gr.Textbox(label="Status", interactive=False, value="Not authenticated")

        # JS for OAuth popup
        login_btn.click(
            fn=lambda: None,
            inputs=[],
            outputs=[],
            _js=f"""
                () => {{
                    const state = Math.random().toString(36).substring(2);
                    window.spotifyState = state;
                    const url = `https://accounts.spotify.com/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri=${{encodeURIComponent('{REDIRECT_URI}')}}&scope=playlist-modify-public playlist-modify-private user-library-read&state=${{state}}`;
                    window.open(url, "_blank");
                }}
            """
        )

        # Listen for message from callback
        gr.HTML("""
        <script>
            window.addEventListener('message', e => {
                if(e.data.token){
                    document.querySelector('#status').value = '✅ Authenticated';
                    window.gradioApp().getComponent('session_token').setValue(e.data.token);
                }
            });
        </script>
        """)

    # ---- Step 2: Upload ----
    with gr.Box(elem_classes="step-box"):
        gr.Markdown("### Step 2: Upload JSON Files")
        files = gr.File(
            label="Upload JSON Files",
            file_types=[".json"],
            file_count="multiple",
            type="binary"
        )

    # ---- Step 3: Generate ----
    with gr.Box(elem_classes="step-box"):
        gr.Markdown("### Step 3: Generate Playlist")
        output_text = gr.Textbox(label="Status")
        output_img = gr.Image(label="Preview (optional)", visible=False)
        generate_btn = gr.Button("Generate Playlist")
        generate_btn.click(
            fn=generate_playlist,
            inputs=[session_token, files],
            outputs=[output_text, output_img]
        )

# ---------------------------
# 🔌 Mount Gradio onto FastAPI
# ---------------------------
app = gr.mount_gradio_app(app, gradio_app, path="/")
