import os
import json
import requests
from typing import List, Tuple, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr

# ---------------------------
# Config (from environment)
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://your-deploy-url.example.com/spotify/callback"  # replace with your real URL or set env
)

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------
# In-memory storage (simple)
# ---------------------------
# NOTE: this is ephemeral and will reset when the server restarts.
SPOTIFY_TOKENS = {
    "access_token": None,
    "refresh_token": None,
    "user_id": None,
    "expires_in": None
}

# ---------------------------
# Spotify helper functions
# ---------------------------
def get_auth_url() -> str:
    scopes = "playlist-modify-public playlist-modify-private user-library-read"
    url = (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scopes}"
        "&show_dialog=true"
    )
    return url

def get_tokens(code: str) -> dict:
    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(token_url, data=payload, timeout=15)
    return resp.json()

def get_user_profile(access_token: str) -> Optional[dict]:
    resp = requests.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if resp.status_code == 200:
        return resp.json()
    return None

def create_spotify_playlist(user_id: str, access_token: str, name: str, description: str, public: bool=True) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"name": name, "description": description, "public": public}
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code in (200, 201):
        return resp.json().get("id"), None
    return None, resp.text

def add_tracks_chunked(playlist_id: str, uris: List[str], access_token: str) -> Tuple[bool, Optional[str]]:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    chunk_size = 100
    for i in range(0, len(uris), chunk_size):
        chunk = uris[i:i+chunk_size]
        resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers=headers,
            json={"uris": chunk},
            timeout=30
        )
        # Spotify returns 201 on success (sometimes 200), consider either OK
        if resp.status_code not in (200, 201):
            return False, resp.text
    return True, None

# ---------------------------
# OAuth callback endpoint
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str = ""):
    """
    Spotify will redirect here with ?code=...
    We exchange code -> access token, store token in-memory, then close popup.
    """
    if not code:
        return {"error": "No code in callback."}
    tokens = get_tokens(code)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")
    if not access_token:
        return {"error": "Failed to get access token", "details": tokens}

    SPOTIFY_TOKENS["access_token"] = access_token
    SPOTIFY_TOKENS["refresh_token"] = refresh_token
    SPOTIFY_TOKENS["expires_in"] = expires_in

    # fetch user profile to keep user id
    profile = get_user_profile(access_token)
    if profile:
        SPOTIFY_TOKENS["user_id"] = profile.get("id")

    # Return a tiny HTML payload that will close the popup tab (works if popup was opened by window.open)
    return """
    <html>
      <head>
        <meta charset="utf-8"/>
      </head>
      <body>
        <script>
          // Close the popup (works if opened by JS window.open)
          window.close();
        </script>
        <p>Authentication complete — you may close this window.</p>
      </body>
    </html>
    """

# ---------------------------
# Playlist generation logic (dedupe, weight by ms_played, cap at 1000)
# ---------------------------
def parse_uploaded_files_to_tracks(files) -> Tuple[List[Tuple[str, int]], Optional[str]]:
    """
    Accepts uploaded files (list of bytes or file-like objects) and returns list of (spotify_uri, ms_played).
    Returns (list, None) on success or ([], error_message) on failure.
    """
    if files is None:
        return [], "No files provided."

    normalized = []
    # Gradio may give list of bytes or objects with read(). Handle both.
    if not isinstance(files, list):
        files = [files]

    for f in files:
        try:
            if hasattr(f, "read"):
                file_bytes = f.read()
            elif isinstance(f, (bytes, bytearray)):
                file_bytes = bytes(f)
            else:
                # Unexpected type
                return [], f"Unsupported file type: {type(f)}"

            # file_bytes may already be str in some environments; ensure bytes
            if isinstance(file_bytes, str):
                file_bytes = file_bytes.encode("utf-8")

            data = json.loads(file_bytes.decode("utf-8"))
            if isinstance(data, dict) and "tracks" in data:
                tracks = data["tracks"]
            elif isinstance(data, list):
                tracks = data
            else:
                tracks = []

            for t in tracks:
                uri = t.get("spotify_track_uri")
                ms_played = t.get("ms_played", 0) or 0
                if uri:
                    normalized.append((uri, int(ms_played)))
        except Exception as e:
            return [], f"Error parsing uploaded file: {e}"

    return normalized, None

def dedupe_and_rank_by_playtime(tracks: List[Tuple[str, int]], cap: int = 1000) -> List[str]:
    """
    Deduplicate by URI keeping highest ms_played for each URI.
    Sort descending by playtime and return list of URIs capped at `cap`.
    """
    track_map = {}
    for uri, ms in tracks:
        # Normalize Spotify URIs to be full spotify:track:... or spotify uri — we keep as-is
        if uri not in track_map or ms > track_map[uri]:
            track_map[uri] = ms

    # Create list of (uri, ms) and sort by ms desc
    sorted_tracks = sorted(track_map.items(), key=lambda kv: kv[1], reverse=True)
    top_uris = [uri for uri, _ in sorted_tracks[:cap]]
    return top_uris

def generate_playlist(files):
    # Check login
    access_token = SPOTIFY_TOKENS.get("access_token")
    user_id = SPOTIFY_TOKENS.get("user_id")
    if not access_token or not user_id:
        return "❌ Please log in to Spotify (Step 1).", None

    # Parse files
    parsed, err = parse_uploaded_files_to_tracks(files)
    if err:
        return f"❌ {err}", None
    if not parsed:
        return "❌ No valid spotify_track_uri entries found in uploaded files.", None

    # Deduplicate & rank by playtime, cap to 1000
    top_uris = dedupe_and_rank_by_playtime(parsed, cap=1000)
    if not top_uris:
        return "❌ No tracks after processing.", None

    # Create playlist
    playlist_name = "Top 1000 — Generated by Listener"
    playlist_description = "Top tracks ranked by total playtime (from your streaming history)."
    playlist_id, create_err = create_spotify_playlist(user_id, access_token, playlist_name, playlist_description, public=False)
    if not playlist_id:
        return f"❌ Failed to create playlist: {create_err}", None

    # Add tracks in chunks
    ok, add_err = add_tracks_chunked(playlist_id, top_uris, access_token)
    if not ok:
        return f"❌ Failed to add tracks: {add_err}", None

    # Get playlist URL
    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    return f"🎉 Playlist created! {len(top_uris)} tracks added. View: {playlist_url}", f"<a href='{playlist_url}' target='_blank'>{playlist_url}</a>"

# ---------------------------
# UI: custom dark CSS + animated pill button
# ---------------------------
CUSTOM_CSS = r"""
/* Dark background, subtle card */
body { background: #0f1113; color: #d7dbe0; }

/* Center container spacing */
.gradio-container { padding: 20px; max-width: 980px; margin: 10px auto; }

/* Card-like panel */
.panel {
    background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
    border-radius: 12px;
    padding: 18px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.6);
    border: 1px solid rgba(255,255,255,0.03);
}

/* Spotify pill button */
.spotify-pill .gr-button {
    background: linear-gradient(90deg, #1DB954, #19c75a);
    color: #fff;
    font-weight: 700;
    border-radius: 999px;
    padding: 12px 26px;
    box-shadow: 0 8px 18px rgba(27,185,76,0.14);
    transition: transform .12s ease, box-shadow .12s ease;
    border: none;
}
.spotify-pill .gr-button:hover {
    transform: translateY(-3px);
    box-shadow: 0 14px 30px rgba(27,185,76,0.20);
}

/* Secondary action button style */
.secondary-btn .gr-button {
    background: transparent;
    border-radius: 8px;
    padding: 8px 12px;
    border: 1px solid rgba(255,255,255,0.06);
    color: #d7dbe0;
}
.secondary-btn .gr-button:hover {
    background: rgba(255,255,255,0.02);
}

/* Steps */
.step {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 10px 0;
}

/* Small status pill */
.status-pill {
    background: rgba(255,255,255,0.03);
    padding: 6px 12px;
    border-radius: 999px;
    font-weight: 600;
    color: #cfead9;
}

/* Small responsive tweaks */
@media (max-width: 600px) {
    .gradio-container { padding: 12px; }
    .spotify-pill .gr-button { padding: 10px 16px; font-size: 14px; }
}
"""

# ---------------------------
# Gradio UI (5.x compatible)
# ---------------------------
with gr.Blocks(title="Spotify — Top 1000 Playlist", css=CUSTOM_CSS) as demo:
    with gr.Column(elem_classes="panel"):
        gr.Markdown("## 🎧 Top 1000 — Playlist Builder", elem_classes="header")
        gr.Markdown("Authenticate with Spotify, upload your Streaming History JSON files, and create a ranked (by playtime) playlist capped at 1000 unique tracks.", elem_classes="sub")

        # Step UI
        with gr.Row(elem_classes="step"):
            with gr.Column(scale=6):
                login_btn = gr.Button("Login with Spotify", elem_classes="spotify-pill")
            with gr.Column(scale=6):
                status_box = gr.Textbox(value="❌ Not logged in", interactive=False, label="Login status", elem_classes="status-pill")
                refresh_btn = gr.Button("Refresh status", elem_classes="secondary-btn")

        gr.Markdown("---")

        gr.Markdown("### Step 2 — Upload JSON files")
        upload_help = gr.Markdown("Upload one or more `YourData/StreamingHistory*.json` files (from Spotify's Download) or other streaming history JSON files.")
        files = gr.File(label="Upload JSON Files", file_count="multiple", file_types=[".json"], type="binary")

        gr.Markdown("### Step 3 — Generate playlist")
        run_btn = gr.Button("Create playlist", elem_classes="spotify-pill")
        output_log = gr.Textbox(label="Status", lines=6)
        playlist_link = gr.HTML()

        # Open Spotify auth popup from main window (popup can be closed by callback)
        auth_url = get_auth_url()
        # Open popup when clicking login_btn
        login_btn.click(fn=lambda: None, inputs=[], outputs=[], js=f"window.open('{auth_url}', '_blank')")

        # Refresh status action
        def check_status():
            return "✅ Logged in" if SPOTIFY_TOKENS.get("access_token") else "❌ Not logged in"
        refresh_btn.click(fn=check_status, inputs=[], outputs=[status_box])

        # Click -> generate playlist
        run_btn.click(fn=generate_playlist, inputs=[files], outputs=[output_log, playlist_link])

# Mount Gradio under FastAPI
app = gr.mount_gradio_app(app, demo, path="/")

# If run directly (for local dev)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
