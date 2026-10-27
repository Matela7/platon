# API AgentRuntimeService

Uruchom `make api`. Swagger: `http://127.0.0.1:8000/docs`.

Przepływ: router → AgentRuntimeService → AgentOrchestrator.
Jedna aplikacja utrzymuje jedną instancję serwisu. Wszystkie endpointy mają
prefix `/api/v1/agent-runtime`.

| Metoda | Ścieżka | Działanie |
|---|---|---|
| POST | `/initialize` | Utworzenie lub otwarcie runtime z konfiguracją |
| GET | `/snapshot` | Historia, interrupty, możliwość retry |
| GET | `/history` | Historia rozmowy |
| GET | `/threads` | Rozmowy z bieżącej bazy |
| GET | `/config` | Obie konfiguracje |
| PUT | `/config` | Zmiana konfiguracji i przebudowanie orchestratora |
| POST | `/chat` | Wiadomość i bezpośredni stream odpowiedzi |
| POST | `/resume` | Odpowiedzi na aktualne interrupty |
| POST | `/retry` | Wznowienie niedokończonej pracy |
| POST | `/stop` | Sygnał zatrzymania |
| POST | `/discard` | Odrzucenie oczekującej pracy |

Inicjalizacja przyjmuje `agent_config`, `orchestrator_config` i opcjonalny
`thread_id`. Korzysta z istniejących modeli konfiguracji. Pominięcie `thread_id`
zachowuje działanie orchestratora: otwarcie ostatniej rozmowy lub utworzenie
nowej, jeśli baza jest pusta. Nową rozmowę można wskazać przez nowe UUID.

Pobierz `GET /config`, zmień wartości i wyślij cały obiekt do `PUT /config`.
Zmiana zachowuje ID rozmowy. Zmiana ścieżki SQLite wybiera inny magazyn,
bez przenoszenia historii. Konfiguracja jest utrzymywana w pamięci aplikacji.

`POST /chat` przyjmuje `{"message":"Treść wiadomości"}`. Chat, resume i retry
zwracają NDJSON: każde zdarzenie orchestratora to osobna linia JSON.
`POST /resume` przyjmuje `{"decisions":{"interrupt-id":{"answer":"..."}}}`
albo decyzje approve/reject zgodne z aktualnym interruptem. Retry, Stop i
discard nie wymagają body.

Stream jest częścią bieżącego requestu. Po jego zerwaniu należy odczytać snapshot
i sprawdzić dostępne wznowienie. Nie ma osobnego rejestru zadań ani replay streamu.
Jedna blokada chroni orchestrator przed równoległym wykonaniem i zmianą konfiguracji;
zajęty runtime zwraca `409`. Stop omija blokadę. Synchroniczne endpointy i stream
FastAPI wykonuje poza event loopem.

`@log_call` loguje przebieg operacji. Nieoczekiwane wyjątki mają stack trace w
logach. Błąd po rozpoczęciu streamu jest zdarzeniem błędu; przed jego rozpoczęciem
może zostać odpowiedzią HTTP. Historia i checkpointy pozostają w SQLite.
