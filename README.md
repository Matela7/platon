# Platon

Projekt jest instalowalnym pakietem `platon-agent`, z kodem w `src/platon`.

## Instalacja i uruchamianie

### Automatyczna instalacja Ollamy

Jeśli Ollama nie jest jeszcze zainstalowana, standalone'owy skrypt przygotuje
ją i pobierze model wymagany przez projekt:

```powershell
python setup_ollama.py --write-env
```

Na Linuxie użyj:

```bash
python3 setup_ollama.py --write-env
```

Dla słabszego komputera można wskazać mniejszy model:

```bash
python setup_ollama.py --model qwen3:8b --write-env
```

Konfiguracja zdalnego serwera Linux przez SSH:

```bash
python setup_ollama.py --remote user@adres-serwera --write-env
```

Skrypt używa kluczy SSH skonfigurowanych w systemie i nie przyjmuje haseł ani
nie zapisuje danych uwierzytelniających. Szczegółowe warianty połączenia opisuje
[instrukcja instalacji Ollamy](docs/ollama-installation.md).

Z katalogu projektu:

```powershell
make build
make run
```

`make build` synchronizuje środowisko z `uv.lock` i buduje pakiet z `src/platon`.
`make run` sprawdza Ollamę, synchronizuje pakiet przez `uv run --locked`
i uruchamia `run_agent_chat_ui.py` z katalogu głównego.

Bez Makefile:

```powershell
uv sync
uv run python -m platon.run_agent_chat
uv run python run_agent_chat_ui.py
```

Moduły można uruchamiać przez pełną nazwę pakietu:

```powershell
uv run python -m platon.vectorstore.chroma_utils
```

Ten moduł uruchamia przykład: ładuje model embeddingów, zapisuje przykładowy
tekst w lokalnej kolekcji Chroma i wykonuje wyszukiwanie.

## Testy i budowanie

```powershell
uv run python -m unittest discover -s tests -v
uv build
```

Prompty są dołączone do pakietu. Dane pozostają względem katalogu roboczego:
`chroma_data/`, `agent_threads.sqlite3` i `.platon/agent/` (pamięć, umiejętności oraz
pliki robocze agenta). Uruchamiaj komendy z katalogu projektu, aby korzystać
z istniejących danych. Konfiguracja środowiska pozostaje w `.env`.

## Układ projektu

- `src/platon/` — kod pakietu i prompty.
- `run_agent_chat_ui.py` — skrypt startowy UI; backend jest w pakiecie.
- `tests/` — testy.
- `docs/architecture.md` — opis architektury.
- `data/documents/` — lokalne dokumenty ze starego katalogu agenta.
- `.platon/agent/` — generowana pamięć i pliki robocze, poza kodem źródłowym.

Własne umiejętności można umieszczać w `.platon/agent/skills/`, a pamięć
w `.platon/agent/memory/AGENTS.md`. `AgentConfig.backend_root` pozwala zmienić
katalog danych. Zależności są zarządzane przez `pyproject.toml` i `uv.lock`.

Przy pierwszym uruchomieniu agent tworzy domyślny katalog `skills/` i plik
`memory/AGENTS.md` w `backend_root`. Istniejąca pamięć pozostaje bez zmian.
Listy `skills=[]` i `memory=[]` wyłączają te źródła. Własne ścieżki muszą istnieć.
