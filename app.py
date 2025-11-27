# app.py
import os
import json
import requests
from collections import Counter
from urllib.parse import urlencode
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr

# ---------------------------
# Spotify credentials (put into env / Render secrets)
# ---------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "REDIRECT_URI",
    "https://spotify-top-1000.onrender.com/spotify/callback"
)

# ---------------------------
# FastAPI app (for OAuth callback)
# ---------------------------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory storage for the short-lived OAuth token + user id
SPOTIFY_TOKENS = {"access_token": None, "user_id": None}


# ---------------------------
# Spotify helpers
# ---------------------------
def get_auth_url():
    scopes = "playlist-modify-public playlist-modify-private user-library-read user-read-recently-played"
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        # PKCE/state can be added for production security
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def exchange_code_for_token(code: str):
    token_url = "https://accounts.spotify.com/api/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    resp = requests.post(token_url, data=data, timeout=15)
    return resp.json()


def get_spotify_profile(access_token: str):
    r = requests.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    if r.status_code == 200:
        return r.json()
    return None


def check_login_status_text():
    return "✅ Logged in" if SPOTIFY_TOKENS.get("access_token") else "❌ Not logged in"


# ---------------------------
# OAuth callback endpoint
# ---------------------------
@app.get("/spotify/callback")
def spotify_callback(code: str = None):
    """
    Spotify redirects the user here with ?code=...
    We exchange the code for a token, keep it in memory, record user id, and close the popup window.
    """
    if code is None:
        return {"error": "No code received"}
    tokens = exchange_code_for_token(code)
    if "access_token" not in tokens:
        # Return a small page so the dev (or user) can see the response
        return {
            "error": "Failed to exchange code for token",
            "details": tokens
        }

    access_token = tokens["access_token"]
    SPOTIFY_TOKENS["access_token"] = access_token
    profile = get_spotify_profile(access_token)
    if profile and profile.get("id"):
        SPOTIFY_TOKENS["user_id"] = profile["id"]

    # Return page that closes popup and notifies user
    # Window will close; user sees alert if popup blockers allow it
    return """
    <script>
      try {
        window.close();
        // If window.close does not work (some browsers), show a message instead:
        setTimeout(()=> {
          document.body.innerHTML = '<h2>Authentication complete — you can close this tab.</h2>';
        }, 200);
      } catch (e) {
        document.body.innerHTML = '<h2>Authentication complete — you can close this tab.</h2>';
      }
    </script>
    """


# ---------------------------
# Core playlist logic
# ---------------------------
def generate_playlist(files):
    """
    files: list of bytes or file-like objects provided by gr.File (type='binary').
    Steps:
      - normalize uploaded files to bytes
      - parse JSON (either list-formatted or object with "tracks")
      - extract spotify_track_uri and ms_played
      - aggregate playtime per track uri
      - remove duplicates (keep summed/maximum - we'll sum total playtime)
      - sort by total playtime descending
      - cap at 1000 tracks
      - create playlist and add tracks in chunks of 100
    """
    access_token = SPOTIFY_TOKENS.get("access_token")
    user_id = SPOTIFY_TOKENS.get("user_id")
    if not access_token or not user_id:
        return "❌ Please login to Spotify first (Step 1).", None

    if not files:
        return "❌ Please upload one or more Spotify streaming history JSON files (Step 2).", None

    # Normalize files into bytes
    normalized_bytes = []
    if not isinstance(files, list):
        files = [files]
    for f in files:
        try:
            # Gradio (binary) gives raw bytes; if it's a file-like object, read bytes
            if hasattr(f, "read"):
                b = f.read()
                normalized_bytes.append(b)
            elif isinstance(f, (bytes, bytearray)):
                normalized_bytes.append(bytes(f))
            else:
                # sometimes Gradio provides a dict/NamedString - try converting
                try:
                    normalized_bytes.append(json.dumps(f).encode("utf-8"))
                except Exception:
                    return "❌ Error: unsupported file input type.", None
        except Exception as e:
            return f"❌ Error reading uploaded file: {e}", None

    # Parse JSON and extract tracks
    playtime_by_uri = Counter()  # sums playtime (ms) per URI
    for fb in normalized_bytes:
        try:
            data = json.loads(fb.decode("utf-8"))
        except Exception as e:
            return f"❌ Error parsing JSON uploaded file: {e}", None

        # Accept either a list of track objects or an object containing "tracks"
        if isinstance(data, dict) and "tracks" in data and isinstance(data["tracks"], list):
            track_list = data["tracks"]
        elif isinstance(data, list):
            track_list = data
        else:
            # Not recognized format — skip
            track_list = []

        for entry in track_list:
            # Expect dictionary-like entries
            if not isinstance(entry, dict):
                continue
            uri = entry.get("spotify_track_uri") or entry.get("spotify_uri") or entry.get("uri")
            ms_played = entry.get("ms_played", 0)
            # Only accept track URIs
            if uri and isinstance(uri, str) and uri.startswith("spotify:track:") and isinstance(ms_played, (int, float)):
                # accumulate total playtime
                playtime_by_uri[uri] += int(ms_played)

    if not playtime_by_uri:
        return "❌ No valid Spotify track URIs found in uploaded files.", None

    # Sort by total playtime desc
    sorted_uris = [uri for uri, _ in playtime_by_uri.most_common()]

    # Cap at 1000 unique tracks
    capped_uris = sorted_uris[:1000]

    # Create playlist in user's account
    playlist_name = "Top 1000 — Generated by Extended History"
    create_payload = {"name": playlist_name, "description": "Ranked by total playtime from exported streaming history.", "public": False}
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=create_payload,
        timeout=15
    )

    if create_resp.status_code not in (200, 201):
        return f"❌ Failed to create playlist: {create_resp.status_code} {create_resp.text}", None

    playlist_id = create_resp.json().get("id")
    playlist_url = create_resp.json().get("external_urls", {}).get("spotify")

    # Add tracks in chunks of 100 (Spotify limit)
    chunk_size = 100
    for i in range(0, len(capped_uris), chunk_size):
        chunk = capped_uris[i:i + chunk_size]
        # Spotify expects list of URIs (e.g. spotify:track:...)
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"uris": chunk},
            timeout=15
        )
        # Spotify will return 201 on success; it may also return 200 depending on API version; treat 201/200 as ok
        if add_resp.status_code not in (200, 201):
            return f"❌ Failed to add tracks (chunk starting at {i}): {add_resp.status_code} {add_resp.text}", None

    success_msg = f"🎉 Playlist created: {playlist_url} ({len(capped_uris)} tracks, unique & capped at 1000)"
    # Return logs and an HTML link so the user can click
    link_html = f"<a href='{playlist_url}' target='_blank'>{playlist_url}</a>" if playlist_url else None
    return success_msg, link_html


# ---------------------------
# UI (Gradio 5.1 compatible)
# ---------------------------
with gr.Blocks(title="Spotify Top 1000 Playlist") as demo:

    # Put visual CSS + JS in an HTML block. Important: sanitize=False so CSS/JS are NOT stripped.
    demo_style = """
    <style>
      body, .gradio-container { background: #121212 !important; color: #fff !important; }
      .panel { background: linear-gradient(180deg, #0f0f0f 0%, #151515 100%); padding: 18px; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.6); }
      .spotify-btn { background: linear-gradient(#1DB954, #1AA34A); color: #ffffff; font-weight:700; border-radius: 28px; padding: 12px 22px; border: none; cursor: pointer; font-size: 16px; box-shadow: 0 6px 22px rgba(29,185,84,0.12); }
      .spotify-btn:hover { transform: translateY(-3px); transition: transform 0.18s ease; box-shadow: 0 12px 30px rgba(29,185,84,0.14); }
      .hero { font-size: 28px; font-weight: 800; margin-bottom: 6px; color: #FFFFFF; }
      .sub { color: #b3b3b3; margin-bottom: 18px; }
      .section { margin-bottom: 18px; }
      .cursor-dot { position: fixed; width: 14px; height: 14px; border-radius: 50%; background: #1DB954; pointer-events: none; z-index: 9999; transform: translate(-50%,-50%); mix-blend-mode: screen; opacity: 0.85; transition: transform 0.05s linear; }
      .spotify-link { color: #1DB954; font-weight:700; text-decoration: none; }
    </style>

    <div class="cursor-dot" id="cursor-dot"></div>

    <script>
      // cursor tracer
      document.addEventListener('mousemove', function(e){
        const d = document.getElementById('cursor-dot');
        if(d){ d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }
      });

      // helper to open popup and focus it
      window.openAuthPopup = function(url) {
        const w = 600, h = 700;
        const left = (screen.width/2)-(w/2);
        const top = (screen.height/2)-(h/2);
        const popup = window.open(url, 'spotify_oauth', `width=${w},height=${h},top=${top},left=${left}`);
        if (popup) popup.focus();
      };
    </script>
    """

    gr.HTML(demo_style, sanitize=False)

    # Header
    with gr.Row(elem_classes="panel"):
        with gr.Column():
            gr.HTML("<div class='hero'>🎵 Spotify — Top 1000 Playlist Builder</div>", sanitize=False)
            gr.HTML("<div class='sub'>Authenticate with Spotify, upload your extended streaming history JSON files, then generate a ranked playlist (unique, capped at 1000).</div>", sanitize=False)

    # Step 1 - Login
    with gr.Row(elem_classes="panel"):
        with gr.Column():
            gr.HTML("<div class='section'><strong>Step 1 — Login</strong></div>", sanitize=False)
            # custom HTML button (so we can control styling). The onclick triggers the popup via the helper.
            auth_url = get_auth_url()
            login_button_html = f"<button class='spotify-btn' onclick=\"window.openAuthPopup('{auth_url}')\">Login with Spotify</button>"
            gr.HTML(login_button_html, sanitize=False)
            status_box = gr.Textbox(value=check_login_status_text(), interactive=False, label="Login status")
            refresh_btn = gr.Button("Refresh status")
            refresh_btn.click(fn=lambda: check_login_status_text(), inputs=None, outputs=[status_box])

    # Step 2 - Upload files
    with gr.Row(elem_classes="panel"):
        with gr.Column():
            gr.HTML("<div class='section'><strong>Step 2 — Upload your Spotify JSON files</strong></div>", sanitize=False)
            files = gr.File(label="Upload JSON files (StreamingHistory/ends, Exported JSON)", file_count="multiple", file_types=[".json"], type="binary")

    # Step 3 - Generate
    with gr.Row(elem_classes="panel"):
        with gr.Column():
            gr.HTML("<div class='section'><strong>Step 3 — Generate playlist</strong></div>", sanitize=False)
            run_btn = gr.Button("🎶 Generate Playlist")
            status_out = gr.Textbox(label="Status / Logs", lines=6)
            playlist_link = gr.HTML(value="", sanitize=False)

            run_btn.click(fn=generate_playlist, inputs=[files], outputs=[status_out, playlist_link])

# mount on FastAPI root
app = gr.mount_gradio_app(app, demo, path="/")
