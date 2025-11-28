import os
import json
import time
import requests
from collections import Counter, defaultdict
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse

import gradio as gr

# -----------------------------
# Config / Environment
# -----------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://spotify-top-1000.onrender.com/spotify/callback")

# Make sure these are set in your host (Render/Heroku/etc.)
if not CLIENT_ID or not CLIENT_SECRET:
    print("WARNING: SPOTIFY_CLIENT_ID and/or SPOTIFY_CLIENT_SECRET not set.")

# -----------------------------
# App initialization
# -----------------------------
api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory storage (simple; ephemeral)
SPOTIFY = {"access_token": None, "refresh_token": None, "expires_at": 0, "user_id": None}

# -----------------------------
# Helpers: OAuth URLs & tokens
# -----------------------------
def get_auth_url():
    scopes = "playlist-modify-public playlist-modify-private user-library-read user-read-private"
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        "show_dialog": "true"
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def exchange_code_for_tokens(code: str):
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


def get_user_profile(access_token: str):
    resp = requests.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code == 200:
        return resp.json()
    return None


def search_spotify_track(access_token: str, name: str, artist: str):
    q = f"track:{name}"
    if artist:
        q += f" artist:{artist}"
    params = {"q": q, "type": "track", "limit": 1}
    resp = requests.get("https://api.spotify.com/v1/search", headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if resp.status_code == 200:
        items = resp.json().get("tracks", {}).get("items", [])
        if items:
            return items[0]["uri"]
    return None


def search_spotify_entity_image(access_token: str, query: str, type_: str):
    # type_ should be "artist" or "album"
    params = {"q": query, "type": type_, "limit": 1}
    resp = requests.get("https://api.spotify.com/v1/search", headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if resp.status_code == 200:
        key = "artists" if type_ == "artist" else "albums"
        items = resp.json().get(key, {}).get("items", [])
        if items and items[0].get("images"):
            return items[0]["images"][0]["url"]
    return None


# -----------------------------
# OAuth callback route
# -----------------------------
@api.get("/spotify/callback")
def spotify_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("<h3>No code returned from Spotify.</h3>")

    tokens = exchange_code_for_tokens(code)
    if "access_token" not in tokens:
        # show the returned error json for debugging
        return JSONResponse(tokens, status_code=400)

    SPOTIFY["access_token"] = tokens["access_token"]
    SPOTIFY["refresh_token"] = tokens.get("refresh_token")
    SPOTIFY["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))

    profile = get_user_profile(SPOTIFY["access_token"])
    if profile and "id" in profile:
        SPOTIFY["user_id"] = profile["id"]

    # Post message to the opener and then attempt to close the window.
    # This works when the popup was opened by JS (window.open).
    html = """
    <html><body>
    <script>
      try {
        window.opener.postMessage({type: "spotify_auth_complete"}, "*");
      } catch (e) {
        // ignore
      }
      // try to close the window (delay helps on some browsers)
      setTimeout(() => { window.open('', '_self'); window.close(); }, 250);
    </script>
    Authentication complete. You can safely close this tab.
    </body></html>
    """
    return HTMLResponse(html)


# -----------------------------
# Small API to check auth status (UI can call)
# -----------------------------
@api.get("/auth_status")
def auth_status():
    return {
        "logged_in": bool(SPOTIFY.get("access_token")),
        "user_id": SPOTIFY.get("user_id")
    }


# -----------------------------
# Utility: load JSON robustly
# -----------------------------
def load_json_file(f):
    """
    Accepts:
     - a filesystem path (str) provided by Gradio
     - bytes (if Gradio returns binary content)
    Returns parsed JSON or None.
    """
    if f is None:
        return None
    try:
        # If path string -> read file
        if isinstance(f, str):
            with open(f, "rb") as fh:
                raw = fh.read()
        elif isinstance(f, bytes):
            raw = f
        else:
            # Some Gradio versions may pass a SpooledTemporaryFile-like object
            # try to read attribute
            if hasattr(f, "read"):
                raw = f.read()
            else:
                return None
        # raw should be bytes
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8"))
        # if already str
        if isinstance(raw, str):
            return json.loads(raw)
    except Exception:
        return None
    return None


# -----------------------------
# Core: Playlist generator
# -----------------------------
def generate_playlist(files):
    access_token = SPOTIFY.get("access_token")
    user_id = SPOTIFY.get("user_id")
    if not access_token or not user_id:
        return "❌ Please log in with Spotify first.", None

    if not files:
        return "❌ No files uploaded.", None

    # Gather (uri, playtime_ms) pairs
    all_pairs = []
    for f in files:
        data = load_json_file(f)
        if not data:
            continue
        # Spotify streaming history can be a list of entries or a dict with "tracks"
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            uri = e.get("spotify_track_uri") or e.get("spotify_uri") or None
            ms = e.get("ms_played", 0) or 0
            name = e.get("master_metadata_track_name") or e.get("track_name") or ""
            artist = e.get("master_metadata_album_artist_name") or e.get("artist_name") or ""
            if uri:
                # ensure spotify:track: format
                all_pairs.append((uri, ms, name, artist))
            else:
                # no URI -> try to search later (store name+artist as fallback)
                all_pairs.append((None, ms, name, artist))

    if not all_pairs:
        return "❌ No playable track data found in uploaded files.", None

    # Resolve URIs where missing (search)
    resolved = []
    for uri, ms, name, artist in all_pairs:
        if uri and uri.startswith("spotify:track:"):
            resolved.append((uri, ms))
            continue
        # attempt to search for a track match
        found = None
        if name:
            found = search_spotify_track(access_token, name, artist)
        if found:
            resolved.append((found, ms))
        else:
            # can't resolve -> skip
            pass

    if not resolved:
        return "❌ No valid Spotify track URIs found (and searches failed).", None

    # Remove duplicates keeping max playtime
    best = {}
    for uri, ms in resolved:
        # Convert uri to canonical spotify:track:id if search returned URI; if API returns full uri or id we accept spotify:track:
        if uri not in best or ms > best[uri]:
            best[uri] = ms

    # Sort by playtime desc
    sorted_by_play = sorted(best.items(), key=lambda x: x[1], reverse=True)

    # Cap at 1000
    capped = [u for u, _ in sorted_by_play[:1000]]

    # Create playlist
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Best 1000 All-Time Tracks", "description": "Generated by Spotify Top 1000 app", "public": False}
    )
    if create_resp.status_code not in (200, 201):
        return f"❌ Failed to create playlist: {create_resp.text}", None
    playlist_id = create_resp.json().get("id")

    # Add in chunks of 100 (Spotify limit)
    for i in range(0, len(capped), 100):
        chunk = capped[i:i + 100]
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"uris": chunk}
        )
        if add_resp.status_code not in (200, 201):
            return f"❌ Failed to add tracks: {add_resp.text}", None

    playlist_url = create_resp.json().get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")
    return f"🎉 Playlist created with {len(capped)} tracks! <a href='{playlist_url}' target='_blank'>{playlist_url}</a>", None


# -----------------------------
# Top Artists & Albums
# -----------------------------
def top_artists(files):
    # Collect playtime per artist
    counter = defaultdict(int)
    for f in files or []:
        data = load_json_file(f)
        if not data:
            continue
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            artist = e.get("master_metadata_album_artist_name") or e.get("artist_name") or None
            ms = e.get("ms_played", 0) or 0
            if artist:
                counter[artist] += ms

    top = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:50]

    # Try to fetch an image for each using Spotify Search
    rows = []
    access_token = SPOTIFY.get("access_token")
    for name, ms in top:
        img = None
        if access_token:
            try:
                img = search_spotify_entity_image(access_token, name, "artist")
            except Exception:
                img = None
        hours = round(ms / (1000 * 60 * 60), 2)
        rows.append({"name": name, "hours": hours, "img": img})

    # Build simple HTML gallery
    html = "<div style='display:flex;flex-wrap:wrap;gap:12px;'>"
    for r in rows:
        imgtag = f"<img src='{r['img']}' style='width:140px;height:140px;object-fit:cover;border-radius:8px;'/>" if r["img"] else f"<div style='width:140px;height:140px;border-radius:8px;background:#222;display:flex;align-items:center;justify-content:center;color:#fff;'>No image</div>"
        html += f"<div style='width:150px;text-align:center'>{imgtag}<div style='margin-top:6px;font-weight:600'>{r['name']}</div><div style='color:#bbb'>{r['hours']} hrs</div></div>"
    html += "</div>"
    return html


def top_albums(files):
    counter = defaultdict(int)
    for f in files or []:
        data = load_json_file(f)
        if not data:
            continue
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            album = e.get("master_metadata_album_album_name") or e.get("album_name") or None
            ms = e.get("ms_played", 0) or 0
            if album:
                counter[album] += ms

    top = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:50]

    rows = []
    access_token = SPOTIFY.get("access_token")
    for name, ms in top:
        img = None
        if access_token:
            try:
                img = search_spotify_entity_image(access_token, name, "album")
            except Exception:
                img = None
        hours = round(ms / (1000 * 60 * 60), 2)
        rows.append({"name": name, "hours": hours, "img": img})

    html = "<div style='display:flex;flex-wrap:wrap;gap:12px;'>"
    for r in rows:
        imgtag = f"<img src='{r['img']}' style='width:140px;height:140px;object-fit:cover;border-radius:6px;'/>" if r["img"] else f"<div style='width:140px;height:140px;border-radius:6px;background:#222;display:flex;align-items:center;justify-content:center;color:#fff;'>No image</div>"
        html += f"<div style='width:150px;text-align:center'>{imgtag}<div style='margin-top:6px;font-weight:600'>{r['name']}</div><div style='color:#bbb'>{r['hours']} hrs</div></div>"
    html += "</div>"
    return html


# -----------------------------
# Gradio UI (compatible with 5.1)
# -----------------------------
with gr.Blocks(title="Spotify Top 1000") as gradio_app:
    gr.Markdown("# 🎵 Spotify Top 1000 & Stats")
    gr.Markdown("Step 1 — click **Login with Spotify** (opens popup). Step 2 — upload your streaming history JSON files. Step 3 — generate playlist or stats.")

    with gr.Tabs():
        with gr.Tab("Playlist"):
            gr.Markdown("### Login")
            login_btn = gr.Button("Login with Spotify")
            status_box = gr.Textbox(value="✅ Logged in!" if SPOTIFY.get("access_token") else "❌ Not logged in", interactive=False)
            refresh_btn = gr.Button("Refresh status")

            # JS listener to receive postMessage from popup and update UI by instructing user to press Refresh
            # (the popup will post message; we rely on Refresh button to fetch /auth_status)
            gr.HTML("""
            <script>
            window.addEventListener("message", (ev) => {
                try {
                    if (ev.data && ev.data.type === "spotify_auth_complete") {
                        // notify the user and close popup if possible
                        setTimeout(()=> {
                            try { window.authPopup && !window.authPopup.closed && window.authPopup.close(); } catch(e){}
                            alert("Spotify authentication completed. Click 'Refresh status' in the app to update.");
                        }, 150);
                    }
                } catch(e){}
            }, false);
            </script>
            """)

            auth_url = get_auth_url()
            # Open popup
            login_btn.click(lambda: None, [], [], js=f"window.authPopup = window.open('{auth_url}', '_blank', 'width=600,height=800')")

            def refresh_status():
                resp = requests.get(f"{os.getenv('BASE_INTERNAL_URL','')}/auth_status") if os.getenv('BASE_INTERNAL_URL') else requests.get("http://127.0.0.1:0" + "/auth_status")  # placeholder; fallback below
                # Instead of interna call, use direct method (we're in same process) — check SPOTIFY dict
                return "✅ Logged in!" if SPOTIFY.get("access_token") else "❌ Not logged in"

            # We will use a local function; no external fetch needed
            refresh_btn.click(lambda: ("✅ Logged in!" if SPOTIFY.get("access_token") else "❌ Not logged in"), [], status_box)

            gr.Markdown("### Upload streaming history (.json)")
            files_input = gr.File(label="Upload JSON files", file_types=[".json"], file_count="multiple", type="binary")

            gr.Markdown("### Generate playlist (top 1000 by playtime)")
            gen_btn = gr.Button("Generate Playlist")
            result_out = gr.Textbox(label="Result (links / errors)", lines=4)
            gen_btn.click(fn=generate_playlist, inputs=[files_input], outputs=[result_out])

        with gr.Tab("Top Artists"):
            gr.Markdown("Upload your streaming history and click below to show Top 50 artists by playtime.")
            a_files = gr.File(file_count="multiple", file_types=[".json"], type="binary")
            a_btn = gr.Button("Show Top 50 Artists")
            a_html = gr.HTML()
            a_btn.click(fn=top_artists, inputs=[a_files], outputs=[a_html])

        with gr.Tab("Top Albums"):
            gr.Markdown("Upload and click to show Top 50 albums by playtime.")
            b_files = gr.File(file_count="multiple", file_types=[".json"], file_count="multiple", type="binary")
            b_btn = gr.Button("Show Top 50 Albums")
            b_html = gr.HTML()
            b_btn.click(fn=top_albums, inputs=[b_files], outputs=[b_html])

# mount gradio app on FastAPI
api = gr.mount_gradio_app(api, gradio_app, path="/")

# If running locally (debug), you can run uvicorn app:api --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
