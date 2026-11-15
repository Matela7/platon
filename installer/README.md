# Platon Installer

This pipeline packages the Electron frontend and a PyInstaller `onefile` backend on all platforms. Linux x64 builds use CPU-only PyTorch instead of the multi-GB CUDA/NVIDIA runtime to reduce package size and avoid overflowing the CArchive 4 GiB limit. Windows and macOS keep their existing dependencies. Linux embeddings run on CPU; Ollama uses its own runtime and can still use a GPU. End users do not need to install Python, Node.js, or uv. The package also includes a separate CPython interpreter for the agent's code execution tools; the PyInstaller executable alone does not replace a general-purpose Python interpreter.

The build targets are Windows x64 (NSIS `.exe` installer), macOS Apple Silicon/ARM64 (`.dmg` and `.zip`), and Linux x64 (AppImage). Build each package on its target operating system. The script accepts macOS 14+ and glibc 2.28+, but CI builds on macOS 15 and Ubuntu 22.04/glibc 2.35. Do not claim that these CI artifacts support older systems without testing them. To release for macOS 14 or glibc 2.28, build on a suitable native machine and verify all ML libraries. This pipeline does not support Intel Macs, native Windows ARM, Linux ARM, or Alpine/musl.

## Building

Build-machine requirements: Git, Node.js 22 with npm, uv, and internet access. Linux also needs AppImage tooling and FUSE support (`libfuse2` on Ubuntu). Building requires several GB of disk space and downloads ML dependencies. Run from the repository root:

```powershell
uv run --no-project --python 3.13 python installer/scripts/build.py
```

The script checks the native architecture, uses `uv.lock` through `uv sync --frozen --no-dev`, installs the pinned PyInstaller 6.16.0, copies managed CPython 3.13, stages the frontend, and runs `npm ci` using the lockfiles. Output is written to `installer/dist`. Use `--dir` to produce an unpacked application for testing, or `--skip-backend` to reuse the existing backend and interpreter. Working files are stored in `installer/staging`.

### Building the next version

From the repository root, `make -C installer release` increments the version and builds the installer. Use `make -C installer build` to rebuild the current version without incrementing it. Inside the `installer` directory, running `make` defaults to the `release` target.

Alternatively, increment the version and build the complete installer with these commands. The first command also updates the lockfile, without creating a Git tag or commit:

```powershell
npm --prefix platon_frontend version patch --no-git-tag-version
uv run --no-project --python 3.13 python installer/scripts/build.py
```

To repeat a build of the same version, run only the second command. For frontend-only changes, you can add `--skip-backend`. After changing Python code or its dependencies, run a full build. On Linux, rebuild once without `--skip-backend` to replace any previous `onedir` or CUDA backend with the CPU-only `onefile` backend. The build automatically removes the previous Linux `onedir` bundle and synchronizes dependencies; you do not need to delete the staging directory or build environment manually.

You can also commit and push your changes, then open **Actions → the workflow for your target system → Run workflow** on GitHub. Once it finishes, download the artifact listed below. Building an installer does not distribute an update to users; you must also publish the package and update metadata from `installer/dist` to the release channel.

Do not copy your personal `.env`, conversation database, models, or account data into the installer. Application data is created in Electron's user-data directory. Ollama models and embedding models are not included in the installer. First launch requires internet access and enough disk space to download the models. Setup downloads `gemma4:e2b-it-qat` and `gemma4:26b-a4b-it-qat`, skipping models that are already installed. Ollama runs as a separate service; the setup screen shows its installation status and download progress. These multi-gigabyte models are not embedded in the `.exe` installer. On Windows, first launch also downloads stable-diffusion.cpp CUDA, Z-Image-Turbo, the Qwen3 encoder, VAE, and Z-Real into the user-data directory. A compatible NVIDIA GPU and CUDA driver are required. Files are verified using SHA-256 checksums, and interrupted downloads can resume after restarting the application. Image generation is skipped on macOS and Linux.

## Updates and releases

Each operating system has its own workflow, available through **Actions → Run workflow**:

| Name in Actions | File in `.github/workflows` | Runner | Artifact |
| --- | --- | --- | --- |
| Windows installer (manual) | `installer-windows.yml` | `windows-2022`, x64 | `platon-windows-x64`: `.exe`, `latest.yml`, blockmap |
| Linux installer (manual) | `installer-linux.yml` | `ubuntu-22.04`, x64 | `platon-linux-x64`: `.AppImage`, `.deb`, `latest-linux.yml`, blockmap |
| macOS installer (manual) | `installer-macos.yml` | `macos-15`, ARM64 | `platon-macos-arm64`: `.dmg`, `.zip`, `latest-mac.yml`, blockmap |

The optional `ref` input selects a branch, tag, or commit to build. Leave it empty to use the commit of the branch selected for the workflow run. Every workflow runs the same backend and frontend tests. The build script also checks the packaged backend through `--self-test`. Artifacts are retained for 14 days. Diagnostic files are saved separately on failure and are not included in the update channel. Builds do not download models or publish releases. The application skips image generation on Linux and macOS.

Set `PLATON_UPDATE_URL` at build time to override the HTTPS update channel. This should point to a directory containing `latest.yml`, `latest-mac.yml`, `latest-linux.yml`, and the release packages. The default is `https://github.com/Matela7/platon/releases/latest/download`; it becomes usable after the packages and manifests are published in that repository. This value is a URL, not an authentication token. Do not embed secrets in the application.

The **All desktop installers (manual)** workflow, `.github/workflows/installer-release.yml`, calls the same three platform workflows for one commit. It does not maintain a separate build implementation without tests. By default, it only builds and saves artifacts. The `publish` option requires an existing tag matching the application version, such as `v0.1.1` for version `0.1.1`. This is checked before the builds start. Only after all three builds succeed are their outputs uploaded to a **draft** GitHub Release in this repository. An existing public release is not overwritten, and the workflow does not automatically publish the draft. Increment the version with `npm --prefix platon_frontend version patch --no-git-tag-version`, commit and push the changes and tag, then verify the packages before publishing the draft. Default builds are unsigned; certificates and secrets are not configured.

The three platform workflows support `workflow_dispatch` and `workflow_call`. A push alone does not start a build. See [GitHub Actions Runner Images](https://github.com/actions/runner-images) for the runner list. The combined workflow uses [reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

macOS updates require the application to be signed with a valid Apple certificate; public distribution should also include notarization. For Windows, configure Authenticode signing and a stable publisher identity before public distribution. AppImage updates replace the application file; verify this on the target Linux distribution. A working channel needs both the new packages and the generated update manifests and blockmap files. Do not change the channel URL without a migration plan for existing installations.

Vendor documentation: [electron-builder publishing](https://www.electron.build/publish/) and [auto-update](https://www.electron.build/v26/docs/features/auto-update/).

## Release verification

On a clean machine without Python or Node.js, run the installer and application. Verify Ollama and model setup, backend readiness, a normal conversation, and application restart with data preserved. Test an update to the next version through the update channel. These checks require native machines for each target. A successful Windows build does not establish that macOS, Linux, or updates from a public server work correctly.

On Linux, first-time Ollama installation requests administrator access through `pkexec` (polkit). If polkit is unavailable, install Ollama beforehand. macOS uses the Ollama application in `/Applications` or `~/Applications`. Windows installation uses winget or the official OllamaSetup.exe. Application updates do not delete the user-data directory, Ollama models, or image generator weights.
