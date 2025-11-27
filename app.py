import gradio as gr

with gr.Blocks(title="Visual Test") as demo:

    gr.HTML("""
    <style>
        body {
            background: #121212 !important;
            color: white !important;
            font-family: 'Inter', sans-serif;
        }

        .spotify-btn {
            background: #1DB954;
            color: black;
            padding: 14px 30px;
            border-radius: 50px;
            font-weight: bold;
            cursor: pointer;
            font-size: 18px;
            border: none;
            display: inline-block;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .spotify-btn:hover {
            transform: scale(1.07);
            box-shadow: 0 0 15px #1DB954;
        }

        .animated-header {
            font-size: 3rem;
            font-weight: 700;
            padding-top: 10px;
            animation: fadeInScale 1s ease-out forwards;
            opacity: 0;
            text-align: center;
        }

        @keyframes fadeInScale {
            0% { opacity: 0; transform: scale(0.8); }
            100% { opacity: 1; transform: scale(1); }
        }

        #cursor-tracer {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #1DB954;
            position: fixed;
            pointer-events: none;
            transform: translate(-50%, -50%);
            z-index: 9999;
        }
    </style>

    <div id="cursor-tracer"></div>

    <script>
        document.addEventListener("mousemove", function(e) {
            let cursor = document.getElementById("cursor-tracer");
            if(cursor){
                cursor.style.left = e.clientX + "px";
                cursor.style.top = e.clientY + "px";
            }
        });
    </script>

    <div class="animated-header">🎵 Spotify Style UI Test</div>
    <br><br>

    <button class="spotify-btn" onclick="alert('Button Clicked!')">
        Login with Spotify
    </button>
    """, sanitize=False)

demo.launch()
