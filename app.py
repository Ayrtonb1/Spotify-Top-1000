# app.py
import os
import json
import time
import requests
from collections import defaultdict
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from starlette.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import gradio as gr

# -------------------------
# Configuration
# -------------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://spotify-top-1000.onrender.com/spotify/callback")

# -------------------------
# Sanity warnings
# -------------------------
if not CLIENT_ID or not CLIENT_SECRET:
    print("WARNING: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET missing in environment.")

# -------------------------
# FastAPI app & CORS
# -------------------------
api = FastAPI()
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# -------------------------
# In-memory token store (ephemeral)
# For production multi-user, replace with DB/session mapping
# -------------------------
SPOTIFY = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": 0,
    "user_id": None,
    "display_name": None,
}

# -------------------------
# Helpers: Spotify OAuth & API
# -------------------------
def get_auth_url():
    scopes = "playlist-modify-public playlist-modify-private user-library-read user-read-private"
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scopes,
        "show_dialog": "true",
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


def spotify_search_first_uri(access_token: str, name: str, artist: str = ""):
    # Try to find a track URI from name + artist
    q = f"track:{name}"
    if artist:
        q += f" artist:{artist}"
    params = {"q": q, "type": "track", "limit": 1}
    resp = requests.get("https://api.spotify.com/v1/search", headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if resp.status_code == 200:
        items = resp.json().get("tracks", {}).get("items", [])
        if items:
            return items[0].get("uri")
    return None


def spotify_search_entity_image(access_token: str, query: str, type_: str):
    # type_ = "artist" | "album"
    params = {"q": query, "type": type_, "limit": 1}
    resp = requests.get("https://api.spotify.com/v1/search", headers={"Authorization": f"Bearer {access_token}"}, params=params)
    if resp.status_code == 200:
        key = "artists" if type_ == "artist" else "albums"
        items = resp.json().get(key, {}).get("items", [])
        if items and items[0].get("images"):
            return items[0]["images"][0]["url"]
    return None


# -------------------------
# OAuth callback route
# -------------------------
@api.get("/spotify/callback")
def spotify_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("<h3>No code returned from Spotify.</h3>")
    tokens = exchange_code_for_tokens(code)
    if "access_token" not in tokens:
        # return error info for debugging
        return JSONResponse(tokens, status_code=400)
    SPOTIFY["access_token"] = tokens["access_token"]
    SPOTIFY["refresh_token"] = tokens.get("refresh_token")
    SPOTIFY["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 3600))
    profile = get_user_profile(SPOTIFY["access_token"])
    if profile:
        SPOTIFY["user_id"] = profile.get("id")
        SPOTIFY["display_name"] = profile.get("display_name")
    # Post message to opener and attempt to close popup
    html = """
    <html><body>
    <script>
      try {
        window.opener.postMessage({type: "spotify_auth_complete"}, "*");
      } catch(e){}
      setTimeout(()=>{ try { window.open('','_self'); window.close(); } catch(e){} }, 200);
    </script>
    Authentication complete. You can safely close this tab.
    </body></html>
    """
    return HTMLResponse(html)


@api.get("/auth_status")
def auth_status():
    return {
        "logged_in": bool(SPOTIFY.get("access_token")),
        "user_id": SPOTIFY.get("user_id"),
        "display_name": SPOTIFY.get("display_name"),
    }


# -------------------------
# Robust JSON loader (handles multiple gr.File return types)
# -------------------------
def load_json_payload(f):
    """
    Accepts:
      - bytes
      - path string (str)
      - file-like object with .read()
      - already-loaded dict/list
    Returns parsed JSON (list or dict) or None
    """
    try:
        if f is None:
            return None
        # If already a Python structure
        if isinstance(f, (dict, list)):
            return f
        # If bytes
        if isinstance(f, bytes):
            return json.loads(f.decode("utf-8"))
        # If path (string)
        if isinstance(f, str):
            with open(f, "rb") as fh:
                raw = fh.read()
            return json.loads(raw.decode("utf-8"))
        # If file-like
        if hasattr(f, "read"):
            raw = f.read()
            # Could be bytes or str
            if isinstance(raw, bytes):
                return json.loads(raw.decode("utf-8"))
            elif isinstance(raw, str):
                return json.loads(raw)
    except Exception:
        return None
    return None


# -------------------------
# Core: generate playlist
# -------------------------
def generate_playlist(files):
    access_token = SPOTIFY.get("access_token")
    user_id = SPOTIFY.get("user_id")
    if not access_token or not user_id:
        return "❌ Please log in with Spotify first.", None

    if not files:
        return "❌ No files uploaded.", None

    # Normalize list
    files_list = files if isinstance(files, (list, tuple)) else [files]

    # Collect (uri, ms_played, name, artist)
    candidates = []
    for f in files_list:
        data = load_json_payload(f)
        if not data:
            continue
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            uri = e.get("spotify_track_uri") or e.get("spotify_uri") or None
            ms = e.get("ms_played", 0) or 0
            name = e.get("master_metadata_track_name") or e.get("track_name") or ""
            artist = e.get("master_metadata_album_artist_name") or e.get("artist_name") or ""
            candidates.append({"uri": uri, "ms": ms, "name": name, "artist": artist})

    if not candidates:
        return "❌ No track data found in uploaded files.", None

    # Resolve missing URIs via search (only if we have a track name)
    resolved = []
    for c in candidates:
        if c["uri"] and (c["uri"].startswith("spotify:") or "open.spotify.com" in c["uri"]):
            # normalize open.spotify.com -> spotify:track:ID
            uri = c["uri"]
            if "open.spotify.com/track/" in uri and "?" in uri:
                # strip query
                uri = uri.split("?")[0]
            if "open.spotify.com/track/" in uri:
                # convert to spotify:track:id
                tid = uri.split("open.spotify.com/track/")[-1].strip("/")
                uri = f"spotify:track:{tid}"
            resolved.append((uri, c["ms"]))
        else:
            # try search if name exists
            if c["name"]:
                found = spotify_search_first_uri(access_token, c["name"], c["artist"])
                if found:
                    resolved.append((found, c["ms"]))
            # otherwise skip
    if not resolved:
        return "❌ No valid Spotify track URIs found (and search fallback failed).", None

    # Deduplicate keeping max ms_played
    best = {}
    for uri, ms in resolved:
        if uri not in best or ms > best[uri]:
            best[uri] = ms

    # Sort by playtime desc
    sorted_by_play = sorted(best.items(), key=lambda kv: kv[1], reverse=True)

    # Cap at 1000 tracks
    capped_uris = [u for u, _ in sorted_by_play[:1000]]

    # Create playlist
    playlist_name = "Best 1000 All-Time Tracks"
    create_resp = requests.post(
        f"https://api.spotify.com/v1/users/{user_id}/playlists",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": playlist_name, "description": "Top 1000 by playtime (generated)", "public": False},
    )
    if create_resp.status_code not in (200, 201):
        return f"❌ Failed to create playlist: {create_resp.text}", None
    playlist_id = create_resp.json().get("id")
    playlist_url = create_resp.json().get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")

    # Add items in chunks of 100
    chunk_size = 100
    for i in range(0, len(capped_uris), chunk_size):
        chunk = capped_uris[i:i + chunk_size]
        add_resp = requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"uris": chunk},
        )
        if add_resp.status_code not in (200, 201):
            return f"❌ Failed to add tracks: {add_resp.text}", None

    return f"🎉 Playlist created with {len(capped_uris)} tracks! <a href='{playlist_url}' target='_blank'>Open in Spotify</a>", None


# -------------------------
# Top artists & albums (by total ms_played)
# -------------------------
def top_artists(files):
    files_list = files if isinstance(files, (list, tuple)) else [files]
    counter = defaultdict(int)
    for f in files_list:
        data = load_json_payload(f)
        if not data:
            continue
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            artist = e.get("master_metadata_album_artist_name") or e.get("artist_name")
            ms = e.get("ms_played", 0) or 0
            if artist:
                counter[artist] += int(ms)
    if not counter:
        return "<div>No artist data found.</div>"
    top50 = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:50]
    access_token = SPOTIFY.get("access_token")
    # Build HTML
    html = "<div style='display:flex;flex-wrap:wrap;gap:12px'>"
    for name, ms in top50:
        hours = round(ms / (1000 * 60 * 60), 2)
        img = None
        if access_token:
            try:
                img = spotify_search_entity_image(access_token, name, "artist")
            except Exception:
                img = None
        if img:
            img_tag = f"<img src='{img}' style='width:140px;height:140px;object-fit:cover;border-radius:8px'/>"
        else:
            img_tag = f"<div style='width:140px;height:140px;border-radius:8px;background:#111;color:#eee;display:flex;align-items:center;justify-content:center'>No image</div>"
        html += f"<div style='width:150px; text-align:center'>{img_tag}<div style='margin-top:6px;font-weight:600'>{name}</div><div style='color:#bbb'>{hours} hrs</div></div>"
    html += "</div>"
    return html


def top_albums(files):
    files_list = files if isinstance(files, (list, tuple)) else [files]
    counter = defaultdict(int)
    for f in files_list:
        data = load_json_payload(f)
        if not data:
            continue
        entries = data.get("tracks") if isinstance(data, dict) and "tracks" in data else (data if isinstance(data, list) else [])
        for e in entries:
            album = e.get("master_metadata_album_album_name") or e.get("album_name")
            ms = e.get("ms_played", 0) or 0
            if album:
                counter[album] += int(ms)
    if not counter:
        return "<div>No album data found.</div>"
    top50 = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:50]
    access_token = SPOTIFY.get("access_token")
    html = "<div style='display:flex;flex-wrap:wrap;gap:12px'>"
    for name, ms in top50:
        hours = round(ms / (1000 * 60 * 60), 2)
        img = None
        if access_token:
            try:
                img = spotify_search_entity_image(access_token, name, "album")
            except Exception:
                img = None
        if img:
            img_tag = f"<img src='{img}' style='width:140px;height:140px;object-fit:cover;border-radius:8px'/>"
        else:
            img_tag = f"<div style='width:140px;height:140px;border-radius:8px;background:#111;color:#eee;display:flex;align-items:center;justify-content:center'>No image</div>"
        html += f"<div style='width:150px; text-align:center'>{img_tag}<div style='margin-top:6px;font-weight:600'>{name}</div><div style='color:#bbb'>{hours} hrs</div></div>"
    html += "</div>"
    return html


# -------------------------
# Gradio UI (compatible with Gradio 5.1)
# -------------------------
with gr.Blocks(title="Spotify Top 1000") as gradio_app:
    gr.Markdown("# 🎵 Spotify Top 1000 & Stats")
    gr.Markdown("Step 1 — click **Login with Spotify** (opens popup). Step 2 — upload your streaming history JSON files. Step 3 — generate playlist or view stats.")

    with gr.Tabs():
        with gr.Tab("Playlist"):
            gr.Markdown("### Login")
            login_btn = gr.Button("Login with Spotify")
            status_box = gr.Textbox(value=("✅ Logged in as " + (SPOTIFY.get("display_name") or "")) if SPOTIFY.get("access_token") else "❌ Not logged in", interactive=False)
            refresh_btn = gr.Button("Refresh status")

            # Listen for postMessage from popup (callback will post message)
            gr.HTML("""
            <script>
            window.addEventListener("message", (ev) => {
                try {
                    if (ev.data && ev.data.type === "spotify_auth_complete") {
                        // try to close popup if still open
                        try { if (window.authPopup && !window.authPopup.closed) window.authPopup.close(); } catch(e){}
                        alert("Spotify authentication completed. Click 'Refresh status' to update the app.");
                    }
                } catch(e){}
            }, false);
            </script>
            """)

            auth_url = get_auth_url()
            # open popup and save reference to window.authPopup
            login_btn.click(lambda: None, [], [], js=f"window.authPopup = window.open('{auth_url}', '_blank', 'width=600,height=800')")

            # refresh button updates status_box by checking SPOTIFY global
            def refresh_status():
                if SPOTIFY.get("access_token"):
                    name = SPOTIFY.get("display_name") or ""
                    return f"✅ Logged in as {name}"
                return "❌ Not logged in"
            refresh_btn.click(refresh_status, [], status_box)

            gr.Markdown("### Upload streaming history (.json)")
            files = gr.File(label="Upload JSON files", file_types=[".json"], file_count="multiple", type="binary")

            gr.Markdown("### Generate playlist (top 1000 by playtime)")
            gen_btn = gr.Button("Generate Playlist")
            result_out = gr.HTML()
            gen_btn.click(generate_playlist, inputs=[files], outputs=[result_out])

        with gr.Tab("Top Artists"):
            gr.Markdown("Upload your streaming history and click below to show Top 50 artists by playtime.")
            a_files = gr.File(file_count="multiple", file_types=[".json"], type="binary")
            a_btn = gr.Button("Show Top 50 Artists")
            a_html = gr.HTML()
            a_btn.click(top_artists, inputs=[a_files], outputs=[a_html])

        with gr.Tab("Top Albums"):
            gr.Markdown("Upload and click to show Top 50 albums by playtime.")
            b_files = gr.File(file_count="multiple", file_types=[".json"], type="binary")
            b_btn = gr.Button("Show Top 50 Albums")
            b_html = gr.HTML()
            b_btn.click(top_albums, inputs=[b_files], outputs=[b_html])

# Mount Gradio onto FastAPI
api = gr.mount_gradio_app(api, gradio_app, path="/")

# Run with: uvicorn app:api --host 0.0.0.0 --port $PORT
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
