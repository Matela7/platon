# Platon.ai

Electron desktop client for the sibling Platon FastAPI backend. Node integration is disabled, the renderer runs sandboxed with context isolation, and the UI is served from a loopback-only server that exposes an explicit list of renderer files and proxies `/api/v1/*` to the configured backend.

## Requirements

- Node.js and npm
- The Platon backend running at `http://127.0.0.1:8000` (default)

From the backend checkout, start it with `make api` or `uv run --locked --python 3.13 python -m platon.backend.app`. Then, from this directory:

```sh
npm install
npm start
```

Set `PLATON_BACKEND_URL` to change the backend origin. To have the desktop app start its own backend process, set `PLATON_BACKEND_DIR` to the backend repository directory; it launches `uv run --locked --python 3.13 python -m platon.backend.app` without a shell. Optionally set `PLATON_UV_EXECUTABLE` to the full path to `uv`. On Windows, quitting asks `taskkill /T` to terminate the `uv` process tree. On macOS and Linux, `uv` runs in a dedicated process group that receives `SIGTERM`; after a grace period, `SIGKILL` is sent only if the tracked `uv` process is still running, to avoid signaling a process-group ID after it may have been reused. If `uv` exits while an independently surviving descendant ignores `SIGTERM`, that descendant may remain. The app does not stop a backend that it did not start.

## Documents and models

In **Dokumenty**, choose an existing document-library collection or **Nowa kolekcja…** when uploading. The collection filter narrows the library without clearing selected documents from other collections. **Użyj w RAG** selects sources for the next message. The chat sends only source metadata and retrieval instructions, with empty `document_ids`, so the backend does not extract and append the full document text. The agent's RAG tools retrieve the evidence; the frontend does not enforce document-level filtering in those tools. Chat history shows readable source names and collections.

**Model Ollama** is a dropdown populated from the configured **Adres Ollama** using Ollama's `/api/tags` endpoint, equivalent to the installed models shown by `ollama list`. Use **Odśwież modele** after installing a model. Connection errors and empty lists are shown beside the selector. The request runs through the desktop client's local server; no Python backend changes are needed.

## Desktop experience

The header language button switches between Polish and English. Desktop preferences (language, theme, last conversation and generated-image associations) are stored in Electron's user-data directory, so changing the local UI port does not reset them. Startup reopens the saved conversation when it exists, otherwise the latest conversation in the backend. **New conversation** starts a fresh thread explicitly.

Generated images appear in the conversation with preview and download actions. Settings provide **Open** buttons next to skills and memory paths; virtual paths such as `/memory/AGENTS.md` resolve inside the configured agent backend root. Opening local resources requires the Electron app and a local backend. Set `PLATON_BACKEND_DIR` when the backend project is outside the frontend's parent directory. Only existing directories and Markdown/text files are opened, using the desktop's default application.

Branding uses a static corgi image and conversation avatars use a different, static side-profile corgi. While waiting or writing, five supplied `pixel-corgi` animations rotate every five seconds, starting with a different animation on successive runs. The indicator disappears when the run finishes and uses a static frame when the system requests reduced motion.

## Packaging

Run `npm run dist:win`, `npm run dist:mac`, or `npm run dist:linux` on the corresponding platform. Artifacts are written to `dist/`. Cross-platform configuration is present; signing and platform builds should be completed on their target operating systems.
