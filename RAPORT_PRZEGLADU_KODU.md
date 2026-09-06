# Przegląd kodu projektu Platon

Data przeglądu: 2026-07-23

## Zakres i sposób oceny

Przejrzano kod Pythona w katalogach `agent/`, `vectorstore/` i `backend/`, skrypty
uruchomieniowe, prompty, `requirements.txt` oraz `.gitignore`. Wykonano także:

- kompilację składniową przez `python3 -m compileall`,
- próbę importu głównych modułów w środowisku `venv2`,
- porównanie zastosowanych wzorców z aktualną dokumentacją LangChain 1.x.

Nie wykonywano zapytań do Ollamy, SerpAPI ani pełnych testów RAG, ponieważ projekt
nie zawiera automatycznych testów, a poprawne wykonanie zależy od lokalnych modeli,
kluczy i usług zewnętrznych.

## Ocena ogólna

Projekt ma sensowny kierunek: oddziela warstwę agenta, routing i magazyn wektorowy,
korzysta z typowanych modeli Pydantic oraz aktualnego `create_agent` w głównym
przepływie. Jest to jednak nadal prototyp, a nie kod gotowy do stabilnego wdrożenia.

Największe ryzyka to:

1. wykonanie polecenia powłoki z tekstu kontrolowanego przez model,
2. kosztowna inicjalizacja modelu embeddingowego już podczas importu modułu,
3. trzy konkurencyjne implementacje `BaseAgent` i osobny, przestarzały przykład,
4. ukrywanie błędów podczas dodawania dokumentów,
5. brak testów, spójnego zarządzania zależnościami i jawnej konfiguracji projektu.

## Mocne strony

### 1. Czytelny podział odpowiedzialności

Kod jest rozdzielony na:

- orkiestrację agenta (`agent/`),
- modele odpowiedzi (`agent/models/`),
- routing (`agent/router_chain_class.py`),
- obsługę ChromaDB (`vectorstore/`),
- skrypty CLI (`run_agent_chat*.py`).

To dobra baza do dalszego wydzielania interfejsów i testowania komponentów osobno.

### 2. Główny agent używa aktualnego API LangChain

`agent/base_agent_class.py` korzysta z:

```python
from langchain.agents import create_agent
```

Jest to rekomendowane API LangChain 1.x. Dobrze wykorzystano także
`with_structured_output(RouterStructuredResponse)` w routerze, zamiast ręcznego
parsowania niestrukturyzowanego tekstu.

Dokumentacja:

- https://docs.langchain.com/oss/python/migrate/langchain-v1#migrate-to-create_agent
- https://docs.langchain.com/oss/python/releases/langgraph-v1#deprecation-of-create_react_agent

### 3. Walidacja danych routingu

`RouterStructuredResponse`:

- ogranicza `route` przez `Literal`,
- waliduje niepusty powód decyzji,
- dostarcza wartość domyślną kodu statusu.

Zmniejsza to liczbę niejawnych przypadków i ułatwia rozwijanie routera.

### 4. Wstrzykiwanie zależności jest częściowo przewidziane

Konstruktory `BaseAgent` przyjmują model, listę narzędzi, `ClientManager` i router.
To dobry punkt wyjścia do testów jednostkowych z atrapami, nawet jeśli obecna
implementacja nie zawsze respektuje przekazane wartości.

### 5. Podstawowa walidacja wejścia i bezpieczne zapytania SQL

W wersjach agenta z historią puste wejście jest odrzucane. Operacje SQLite używają
parametrów zapytania, a nie interpolacji tekstu. Wyszukiwanie wektorowe również
sprawdza pusty tekst zapytania.

### 6. Separacja promptów od kodu

Prompty znajdują się w `agent/prompts/`, a `prompt_loader.py` ładuje je względem
położenia modułu. Ułatwia to edycję promptów, przegląd zmian oraz przyszłe testy
promptów bez mieszania ich z logiką Pythona.

### 7. Repozytorium chroni typowe dane lokalne

`.env`, katalogi środowisk, ChromaDB i pliki PDF są ignorowane przez Git. To dobry
fundament ochrony kluczy i danych użytkownika.

## Słabe strony i ryzyka

### P0 — bezpieczeństwo: możliwość command injection

`agent/tools.py:49-52` buduje polecenie w ten sposób:

```python
return ShellTool().run(f"ls {path}")
```

`path` pochodzi z argumentu narzędzia i może zawierać operatory powłoki. Model lub
treść prompt injection w dokumencie może więc doprowadzić do wykonania dodatkowych
poleceń na hoście. Jest to szczególnie groźne, ponieważ narzędzie trafia do domyślnej
listy narzędzi każdego agenta.

Rekomendacja:

- jeśli potrzebne jest tylko listowanie, usunąć `ShellTool` i użyć
  `Path(path).iterdir()` po walidacji, że ścieżka leży w dozwolonym katalogu;
- jeśli naprawdę potrzebna jest powłoka, użyć aktualnego
  `ShellToolMiddleware` z jawną polityką wykonania i izolacją;
- dla narzędzi zapisujących dane dodać zatwierdzanie przez człowieka.

Aktualna dokumentacja ostrzega, że narzędzia powłoki wymagają odpowiedniej polityki
wykonania:
https://docs.langchain.com/oss/python/langchain/middleware/built-in#shell-tool

### P0 — efekt uboczny importu i zależność od sieci

`vectorstore/chroma_utils.py:10` tworzy `SentenceTransformer` globalnie:

```python
model = SentenceTransformer("all-MiniLM-L6-v2")
```

W efekcie samo `import agent.base_agent_class` inicjalizuje ciężki model i może
próbować pobrać pliki z Hugging Face. Próba importu podczas przeglądu zakończyła
się wielokrotnymi błędami DNS i długim oczekiwaniem.

Skutki:

- wolny start CLI i testów,
- import nie działa offline, jeśli model nie jest w cache,
- trudne testowanie bez dużej zależności ML,
- niekontrolowane zużycie pamięci,
- procesy robocze mogą niezależnie ładować tę samą wagę modelu.

Rekomendacja: wprowadzić leniwą fabrykę z cache, np. `@lru_cache`, oraz przekazywać
interfejs embeddera do `CollectionStore`/`ClientManager`. Nazwę modelu i tryb
offline umieścić w typowanej konfiguracji.

### P1 — przekazany model jest ignorowany

W każdej wersji `BaseAgent.__init__` przypisywane jest `self.model = model`, po czym
bezwarunkowe `_setup_model()` natychmiast zastępuje przekazany obiekt nowym
`ChatOllama`. To łamie deklarowany mechanizm dependency injection.

Rekomendacja:

```python
if self.model is None:
    self._setup_model()
```

Model routera również powinien być osobną zależnością lub mieć osobną nazwę w
konfiguracji. Obecnie główny agent przekazuje ten sam `model_name` agentowi i
routerowi, mimo że router zwykle powinien używać mniejszego, szybszego modelu.

### P1 — wiele konkurencyjnych implementacji

W repozytorium są:

- `agent/base_agent_class.py`,
- `agent/base_agent_class_memory.py`,
- `agent/base_agent_class copy.py`,
- `agent/agent.py`,
- dwa skrypty `run_agent_chat*.py`.

Plik ze spacją jest ładowany dynamicznie przez `importlib`, co omija normalne
mechanizmy importowania i utrudnia analizę statyczną. Nie wiadomo, która wersja
definiuje docelową architekturę. Poprawki będą łatwo trafiały tylko do jednej kopii.

`agent/agent.py` dodatkowo wykonuje przykładowe zapytanie już przy imporcie oraz
używa starego `create_react_agent`.

Rekomendacja:

- zachować jeden `BaseAgent`,
- pamięć i routing włączać przez składane komponenty/konfigurację,
- przykład przenieść do `examples/` i osłonić `if __name__ == "__main__":`,
- usunąć pliki `copy` po przeniesieniu potrzebnej funkcjonalności,
- pozostawić jeden oficjalny entry point CLI.

### P1 — ukrywanie błędów

`ClientManager.add_document_to_collection()` przechwytuje każde `Exception` i
zwraca tylko `False`. Tracone są typ błędu, komunikat, stos i informacja przydatna
operatorowi. Z kolei inne miejsca łapią bardzo szerokie wyjątki i opakowują je,
co może utrudnić obsługę konkretnych przypadków.

Rekomendacja:

- przechwytywać tylko oczekiwane wyjątki,
- logować wyjątek przez `logging.exception`,
- zwracać typowany wynik z kodem błędu albo pozwolić wyjątkom domenowym przejść wyżej,
- zachowywać przyczynę przez `raise ... from exc`.

### P1 — brak granic dostępu do plików

Narzędzie `add_document_to_collection` przyjmuje dowolny `file_path`. Agent może
próbować odczytać dowolny plik dostępny dla procesu. Samo użycie `Path(file_path).name`
w nieużywanej metodzie `_save_uploaded_file` nie rozwiązuje problemu odczytu.

Rekomendacja: utworzyć jeden dozwolony katalog importu, rozwiązywać ścieżki przez
`Path.resolve()` i sprawdzać `is_relative_to(allowed_root)`. Rozważyć zatwierdzanie
operacji dodawania dokumentu przez użytkownika.

### P1 — pamięć rozmowy ma niespójny model własności

`base_agent_class_memory.py` łączy:

- ręcznie przekazywaną historię,
- checkpointer LangGraph,
- osobny zapis tej samej historii do SQLite.

Grozi to duplikowaniem wiadomości i rozjazdem między trzema źródłami prawdy.
`InMemorySaver` nie daje trwałości po restarcie, mimo że obok istnieje własna baza
SQLite. Plik zapisuje historię, ale nie udostępnia kompletnego API jej odczytu.

Rekomendacja: wybrać jedno źródło prawdy. Dla pamięci krótkoterminowej użyć
checkpointera i `thread_id`; trwałość zapewnić wspieranym trwałym checkpointerem.
Przycinanie historii realizować przez middleware `before_model`, a dłuższe rozmowy
przez `SummarizationMiddleware`.

Dokumentacja:

- https://docs.langchain.com/oss/python/langchain/short-term-memory#trim-messages
- https://docs.langchain.com/oss/python/releases/langchain-v1#prebuilt-middleware

### P1 — niepoprawna semantyka limitu historii

W kopiach agenta `max_history_messages` jest przekazywane jako `max_tokens`, a
`token_counter=len` liczy wiadomości, nie tokeny. Nazwa sugeruje limit wiadomości,
ale interfejs `trim_messages` traktuje wartość jako budżet zależny od licznika.

Rekomendacja: albo nazwać parametr `max_history_messages` i wykonać jawne cięcie
listy, albo używać rzeczywistego licznika tokenów modelu i nazwy
`max_history_tokens`. W nowej architekturze przenieść tę logikę do middleware.

### P1 — zależności nie są odtwarzalne na podstawie projektu

Kod importuje `langchain_ollama`, ale `requirements.txt` nie zawiera jawnego
`langchain-ollama`. Plik wygląda jak pełny `pip freeze` środowiska, a nie lista
bezpośrednich zależności aplikacji. Zawiera ponad sto pakietów, kilka providerów
LLM i ciężkie biblioteki niezwiązane bezpośrednio z każdym trybem działania.

Brakuje także:

- `pyproject.toml` z metadanymi i minimalną wersją Pythona,
- rozdzielenia zależności runtime/dev,
- narzędzi jakości (`ruff`, `mypy`/`pyright`, `pytest`),
- kontrolowanego procesu aktualizacji zależności.

Rekomendacja: zdefiniować minimalne zależności bezpośrednie w `pyproject.toml`,
utrzymywać osobny lockfile i grupę `dev`. Integracje providerów instalować jako
opcjonalne extras, jeśli projekt ma obsługiwać kilka backendów.

### P2 — błędy i nieprecyzyjne typowanie modeli Pydantic

W `AgentStructuredResponse`:

```python
source: list[str | None] = None
```

Typ nie dopuszcza `None`, chociaż wartość domyślna nim jest. Prawdopodobnie
oczekiwano `list[str] | None = None` albo bezpieczniej `list[str] =
Field(default_factory=list)`.

W `AgentStructuredArtifact` użyto dekoratora/funkcji `tool` jako typu pola.
Walidator `tool_used` sprawdza obecność pola `tool_used` podczas walidacji właśnie
tego pola, co jest logicznie błędne i bazuje na starej sygnaturze walidatorów.
Lepszy będzie `BaseTool`, nazwa narzędzia jako `str` lub osobny model metadanych.

Modele `AgentStructuredResponse` i `AgentStructuredArtifact` nie są obecnie używane
w głównym przepływie, co zwiększa ryzyko ich cichego starzenia.

### P2 — problemy z obsługą plików i danych

- Rozszerzenie jest pobierane przez `file_path.split('.')[-1]`; lepsze jest
  `Path(file_path).suffix.lower()`.
- Brakuje limitu rozmiaru pliku, liczby stron i liczby chunków.
- Pusty PDF/DOCX może prowadzić do kodowania pustej listy.
- DOCX traci strukturę tabel i nagłówków.
- Numer strony PDF jest zerowany, co może dawać nieintuicyjne cytowania.
- Metadane nie zawierają stabilnego identyfikatora dokumentu ani wersji.
- Ponowne dodanie tego samego pliku tworzy nowe UUID i duplikaty.
- Nie ma transakcyjnego zachowania: błąd w połowie PDF może pozostawić część chunków.

Rekomendacja: wprowadzić pipeline `load -> normalize -> split -> embed -> upsert`,
stabilne ID oparte o hash dokumentu/chunku, walidację limitów i strategię rollbacku
lub staging collection.

### P2 — wynik podobieństwa może być mylący

`similarity = 1 - distance` zakłada konkretną metrykę i zakres odległości. Dla
innej przestrzeni/metryki wartość nie musi być prawdopodobieństwem ani mieścić się
w przedziale 0–1.

Rekomendacja: zwracać jawnie `distance` oraz nazwę metryki. Jeśli potrzebny jest
znormalizowany score, transformację uzależnić od skonfigurowanej funkcji odległości
i nazwać ją precyzyjnie.

### P2 — routing analizuje całą historię użytkownika jako jeden tekst

`RouterChain.invoke()` scala wszystkie wiadomości użytkownika. Stare pytania mogą
więc zmienić trasę nowego pytania. Systemowe i asystenckie elementy kontekstu są
pomijane.

Rekomendacja: routować przede wszystkim ostatnią wiadomość, a potrzebny kontekst
przekazywać w osobnym, ograniczonym polu. Decyzję routera warto mierzyć w testach na
ustalonym zestawie przypadków.

### P2 — synchroniczne i blokujące operacje

Wywołania modelu, embeddingów, ChromaDB, odczytu dokumentów i SerpAPI są
synchroniczne. Dla CLI jest to akceptowalne, ale przyszły backend HTTP będzie
blokował worker.

Rekomendacja: najpierw ustalić docelowy sposób wdrożenia. Dla API dodać kontrolowaną
warstwę async lub wykonywać zadania CPU/IO w workerze, z timeoutami i anulowaniem.

### P2 — brak obserwowalności i diagnostyki

Kod używa `print`, szerokich wyjątków i rozpoznawania DNS po fragmencie komunikatu
`"Errno 8"`. Brakuje ustrukturyzowanych logów, metryk liczby chunków, czasu
embeddingu, decyzji routera i błędów narzędzi.

Rekomendacja: użyć standardowego `logging`, korelować logi przez `run_id` i
`thread_id`, nie logować treści dokumentów ani sekretów, a błędy sieci klasyfikować
po typach wyjątków.

### P2 — nieużywane importy, pola i kod

Przykłady:

- `ChatOpenAI`, `ChatPromptTemplate`, `MessagesPlaceholder`,
  `CollectionStore` w `agent/tools.py`,
- `working_dir`, `memory`, `prompts` w głównym `BaseAgent`,
- `_save_uploaded_file`,
- duży blok zakomentowanego kodu w `agent/tools.py`,
- pusty katalog logiczny `backend/`.

To nie jest tylko kosmetyka: zaciemnia faktyczną architekturę i utrudnia określenie
minimalnych zależności.

## Aktualizacja do nowych standardów LangChain

### Już zgodne

- Główny `BaseAgent` używa `langchain.agents.create_agent`.
- Router używa strukturyzowanej odpowiedzi Pydantic.
- `system_prompt` jest przekazywany zgodnie z API LangChain 1.x.
- Narzędzia są dekorowane przez `@tool`.

### Do aktualizacji

1. `agent/agent.py` migrować z `create_react_agent` do `create_agent`.
2. Przycinanie/sumaryzację pamięci przenieść do middleware.
3. Obsługę błędów narzędzi realizować przez `wrap_tool_call`, zamiast ogólnych
   `try/except` ukrywających kontekst.
4. Dla niebezpiecznych narzędzi zastosować `HumanInTheLoopMiddleware`.
5. Rozważyć `PIIMiddleware`, jeśli do modeli lub wyszukiwarki trafiają dokumenty
   użytkownika.
6. Jeśli narzędzia będą potrzebować stanu lub kontekstu uruchomienia, używać
   `ToolRuntime`, a nie dokładania parametrów kontrolowanych przez model.
7. Jeśli wymagany jest ustrukturyzowany finalny wynik agenta, użyć
   `response_format` z `ToolStrategy`/`ProviderStrategy`, zamiast nieużywanych
   modeli wynikowych obok przepływu.

Dokumentacja migracji wskazuje, że w LangChain 1.x dynamiczne prompty, przycinanie,
obsługa błędów narzędzi i kontrola wywołań powinny być realizowane przez middleware:
https://docs.langchain.com/oss/python/migrate/langchain-v1#migrate-to-create_agent

## Proponowana architektura docelowa

```text
CLI / przyszłe API
        |
        v
ApplicationService
  - walidacja żądania
  - thread_id / run_id
  - wybór trasy
        |
        +--> AgentFactory
        |      - model agenta
        |      - model routera
        |      - middleware
        |      - bezpieczny zestaw narzędzi
        |
        +--> DocumentService
               - dozwolony katalog
               - loader registry
               - splitter
               - Embedder (wstrzykiwany, lazy)
               - VectorStoreRepository
```

Konfiguracja powinna być jednym typowanym obiektem (np. `pydantic-settings`), a nie
zbiorem wartości domyślnych rozproszonych między klasami i skryptami.

## Plan refaktoryzacji

### Etap 1 — bezpieczeństwo i uruchamialność

1. Usunąć `execute_ls_command` oparte na `ShellTool` albo zastąpić je bezpiecznym
   listowaniem ograniczonym do workspace.
2. Ograniczyć ścieżki odczytu dokumentów do jednego katalogu.
3. Zmienić globalny `SentenceTransformer` na leniwie inicjalizowaną zależność.
4. Dodać brakujące bezpośrednie zależności, przede wszystkim `langchain-ollama`.
5. Nie wykonywać zapytań ani inicjalizacji usług podczas importu modułów.

Kryterium ukończenia: import wszystkich pakietów działa offline bez uruchamiania
modeli i bez prób połączenia sieciowego.

### Etap 2 — konsolidacja

1. Wybrać jeden `BaseAgent`.
2. Połączyć routing i pamięć jako opcjonalne komponenty.
3. Usunąć `base_agent_class copy.py` i przenieść przykład z `agent/agent.py`.
4. Zostawić jeden CLI i jedną ścieżkę konfiguracji.
5. Usunąć martwy kod i nieużywane importy.

Kryterium ukończenia: istnieje jedna publiczna fabryka agenta i jeden oficjalny
punkt uruchomienia.

### Etap 3 — testy i kontrakty

Minimalny zestaw testów:

- `prompt_loader` — poprawny i brakujący plik,
- router — każda trasa, pusty/niepoprawny wynik modelu,
- walidacja ścieżek i rozszerzeń dokumentów,
- pusty PDF/DOCX/TXT,
- deterministyczne ID i brak duplikacji przy ponownym imporcie,
- globalne sortowanie wyników wielu kolekcji,
- błąd embeddera/ChromaDB nie jest ukrywany,
- historia nie dubluje wiadomości,
- agent nie dostaje narzędzi niedozwolonych dla danej trasy.

W testach używać atrap modelu, embeddera i klienta ChromaDB. Testy jednostkowe nie
powinny pobierać modeli ani wymagać Ollamy.

### Etap 4 — nowoczesny tooling Pythona

1. Dodać `pyproject.toml`.
2. Ustalić wspieraną wersję Pythona (rozsądnie 3.11–3.13 po sprawdzeniu bibliotek).
3. Dodać `ruff format`, `ruff check`, `pytest` i `pyright` albo `mypy`.
4. Uruchamiać je w CI.
5. Dodać README z konfiguracją Ollamy, SerpAPI, Hugging Face cache i ChromaDB.
6. Dodać przykład `.env.example` bez sekretów.

### Etap 5 — jakość RAG i eksploatacja

1. Wersjonować konfigurację embeddingów i chunkowania.
2. Dodać stabilne identyfikatory oraz idempotentny `upsert`.
3. Zapisywać źródło, stronę i hash dokumentu w metadanych.
4. Dodać timeouty, retry tylko dla błędów przejściowych i limity wejścia.
5. Wprowadzić ewaluacje retrievalu i odpowiedzi na stałym zbiorze pytań.
6. Dodać obserwowalność bez ujawniania treści dokumentów i sekretów.

## Szybkie poprawki o dobrym stosunku efektu do kosztu

- Zamienić `list[tool] = None` na poprawne `Sequence[BaseTool] | None = None`.
- Nie nadpisywać modelu przekazanego w konstruktorze.
- Użyć `Path.suffix`, `Path.resolve` i walidacji katalogu bazowego.
- Zamienić `os.path` i ręczne `open()` na spójne użycie `pathlib`.
- Dodać `raise ... from exc`.
- Usunąć nieużywane importy i zakomentowane implementacje.
- Zmienić `source` na `list[str] = Field(default_factory=list)`.
- Ustawić jawne `temperature=0` dla routera i oddzielny model routera.
- Walidować `n_results > 0` i nakładać maksymalny limit.
- Zwracać nazwę metryki wraz z `distance`, bez udawania prawdopodobieństwa.

## Weryfikacja wykonana podczas przeglądu

- `python3 -m compileall`: zakończone powodzeniem — brak błędów składni.
- Import głównych modułów w `venv2`: nie zakończył się poprawnie offline, ponieważ
  import `vectorstore.chroma_utils` próbował pobierać/weryfikować model
  `all-MiniLM-L6-v2` w Hugging Face.
- Automatyczne testy: brak plików testowych w repozytorium.

## Priorytet końcowy

Najpierw należy usunąć ryzyko wykonania dowolnych poleceń i efekty uboczne importu.
Następnie warto skonsolidować wersje agenta i dopiero na jednej, testowalnej
architekturze rozwijać pamięć, routing oraz jakość RAG. Aktualizowanie poszczególnych
kopii bez tej konsolidacji zwiększy koszt utrzymania i prawdopodobnie wprowadzi
kolejne rozbieżności.
