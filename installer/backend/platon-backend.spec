"""Build on each target OS: python -m PyInstaller --clean --noconfirm ..."""
from pathlib import Path
from importlib.util import find_spec
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
datas = [(str(root / "src" / "platon" / "agent" / "prompts"), "platon/agent/prompts")]
binaries = []
hiddenimports = []
# Dynamic imports, native libraries and distribution metadata used by the stack.
for package in ("chromadb", "sentence_transformers", "transformers", "tiktoken", "onnxruntime", "tokenizers", "langchain", "langchain_community", "langchain_ollama", "langgraph", "deepagents", "fastmcp"):
    print(f"Collecting resources: {package}", flush=True)
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
def modules_from_files(package):
    spec = find_spec(package)
    if spec is None:
        return []
    modules = [package]
    for location in spec.submodule_search_locations or []:
        for file in Path(location).rglob("*.py"):
            parts = file.relative_to(location).with_suffix("").parts
            if "tests" in parts:
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules.append(".".join((package, *parts)))
    return modules

for package in ("deepagents", "langgraph", "langchain_ollama", "fastmcp", "tiktoken_ext"):
    print(f"Collecting modules: {package}", flush=True)
    hiddenimports += modules_from_files(package)
hiddenimports += ["chromadb.api.rust", "chromadb.segment.impl.vector.local_persistent_hnsw", "chromadb.telemetry.product.posthog", "transformers.models.qwen3.modeling_qwen3", "transformers.models.qwen3.configuration_qwen3"]
# PyInstaller 6.16's SciPy hook predates the 1.17 extension and the 1.18
# relocation of array_api_compat. These imports are resolved dynamically.
hiddenimports += ["scipy._cyutility", "scipy._external.array_api_compat.numpy.fft"]
for distribution in ("langchain-core", "langchain", "langgraph", "deepagents", "chromadb", "sentence-transformers", "transformers", "pydantic", "fastmcp"):
    datas += copy_metadata(distribution, recursive=True)
hiddenimports += modules_from_files("platon")
hiddenimports += ["uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"]
a = Analysis([str(root / "installer" / "backend" / "entrypoint.py")], pathex=[str(root / "src")], binaries=binaries, datas=datas, hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
# The Linux installer uses CPU-only torch to keep this CArchive below 4 GiB.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="platon-backend", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
