# Backend dla aplikacji Electron

> Docelowa specyfikacja lokalnego backendu Platona przeznaczonego do współpracy z aplikacją Electron.
>
> Status: propozycja architektury. Dokument opisuje kierunek rozwoju, a nie gotowy kontrakt implementacyjny.

## 1. Cel

Backend ma być niezależnym procesem uruchamianym i zarządzanym przez aplikację Electron. Electron odpowiada za prezentację, nawigację i interakcje użytkownika, natomiast backend pozostaje właścicielem:

- orkiestracji agentów i delegowania zadań;
- sesji rozmów oraz checkpointów LangGraph;
- operacji RAG i lokalnego magazynu dokumentów;
- kontroli zgód użytkownika przed działaniami wrażliwymi;
- konfiguracji Ollama, MCP, Gmaila i narzędzi lokalnych;
- logowania, anulowania, ponawiania i bezpiecznego zamykania procesów.

Najważniejsza zasada: Electron nie powinien bezpośrednio importować modułów agenta ani otwierać plików SQLite, ChromaDB lub sekretów. Komunikacja z backendem powinna odbywać się przez stabilny kontrakt transportowy.

## 2. Docelowy model procesu

```text
┌──────────────────────────────┐
│ Electron renderer             │
│ React/Vue/Svelte/UI           │
└──────────────┬───────────────┘
               │ IPC w Electronie
┌──────────────▼───────────────┐
│ Electron main process         │
│ - start/stop backendu         │
│ - lifecycle i health check    │
│ - bezpieczny bridge           │
└──────────────┬───────────────┘
               │ localhost HTTP + NDJSON
┌──────────────▼───────────────┐
│ Platon backend                │
│ - aiohttp API                 │
│ - AgentOrchestrator           │
│ - SupervisorAgent             │
│ - ConversationStore           │
│ - approvals / streaming       │
└───────┬───────────┬───────────┘
        │           │
┌───────▼──────┐ ┌──▼───────────────┐
│ Ollama       │ │ lokalne dane     │
│ localhost    │ │ SQLite/Chroma    │
└──────────────┘ └──────────────────┘
```

### 2.1. Granice odpowiedzialności

| Element | Odpowiedzialność |
|---|---|
| Renderer | Widoki, formularze, lista rozmów, prezentacja streamu i zgód |
| Electron main | Uruchomienie backendu, przydzielenie portu, token sesyjny, IPC |
| Backend | Cała logika biznesowa, agenci, persistence, walidacja i autoryzacja |
| Ollama | Lokalna inferencja modelu |
| MCP/Gmail | Opcjonalny zewnętrzny dostawca narzędzi, uruchamiany przez backend |

Renderer nie otrzymuje dostępu do `child_process`, filesystemu, SQLite ani zmiennych środowiskowych. W Electronie należy utrzymać `contextIsolation: true`, `nodeIntegration: false` i wąski `preload` API.

## 3. Uruchomienie backendu przez Electron

Electron main process powinien:

1. znaleźć interpreter lub spakowany launcher backendu;
2. przydzielić wolny port na `127.0.0.1`;
3. wygenerować jednorazowy token sesyjny w pamięci;
4. uruchomić backend z przekazanym portem i tokenem;
5. poczekać na `GET /health/ready`;
6. przekazać rendererowi wyłącznie bazowy URL i funkcje bridge;
7. zakończyć backend przy zamykaniu aplikacji.

Przykładowe argumenty procesu:

```text
python -m platon.backend.server \
  --host 127.0.0.1 \
  --port <dynamic-port> \
  --session-token <ephemeral-token>
```

Token nie powinien być zapisywany w pliku, URL-u, historii rozmowy ani logach. Jeżeli backend nie wystartuje w określonym czasie, Electron powinien pokazać konkretny komunikat diagnostyczny zamiast udawać gotowość.

### 3.1. Health checks

- `GET /health/live` — proces odpowiada.
- `GET /health/ready` — backend załadował konfigurację i może przyjmować żądania.
- `GET /health/details` — informacje techniczne dla ekranu diagnostycznego; bez sekretów i bez pełnych ścieżek wrażliwych.

Backend powinien zwracać status `503`, gdy nie jest gotowy, zamiast zwracać sukces z pustymi danymi.

## 4. Kontrakt API

Wersjonowanie powinno być jawne, np. `/api/v1`. Format błędów powinien być jednolity:

```json
{
  "error": {
    "code": "pending_approval",
    "message": "Resolve the pending approval before starting another request.",
    "request_id": "..."
  }
}
```

`message` może być wyświetlony użytkownikowi, ale stack trace, tokeny i dane uwierzytelniające nigdy nie mogą być wysyłane do klienta.

### 4.1. Rozmowy

| Metoda | Endpoint | Znaczenie |
|---|---|---|
| `GET` | `/api/v1/conversations` | Lista zapisanych rozmów |
| `POST` | `/api/v1/conversations` | Utworzenie nowej rozmowy |
| `GET` | `/api/v1/conversations/{thread_id}` | Historia rozmowy i stan |
| `DELETE` | `/api/v1/conversations/{thread_id}` | Usunięcie rozmowy po potwierdzeniu |
| `POST` | `/api/v1/conversations/{thread_id}/messages` | Rozpoczęcie odpowiedzi ze streamingiem |
| `POST` | `/api/v1/conversations/{thread_id}/resume` | Odpowiedź na pytanie lub zgodę |
| `POST` | `/api/v1/conversations/{thread_id}/retry` | Ponowienie niedokończonego runu |
| `POST` | `/api/v1/conversations/{thread_id}/stop` | Żądanie zatrzymania aktywnego runu |
| `POST` | `/api/v1/conversations/{thread_id}/discard` | Odrzucenie niedokończonego stanu |

Backend powinien odrzucić nową wiadomość, gdy rozmowa ma nierozwiązaną zgodę, pytanie lub aktywny checkpoint wymagający wznowienia. Nie należy automatycznie kasować stanu w celu "naprawienia" żądania.

### 4.2. Wysyłanie wiadomości

Żądanie:

```json
{
  "content": "Przeszukaj dokumenty dotyczące projektu.",
  "client_message_id": "uuid-generated-by-electron"
}
```

Odpowiedź nie powinna być pojedynczym JSON-em oczekującym na zakończenie modelu. Backend powinien zwracać `application/x-ndjson`, a każda linia powinna być samodzielnym zdarzeniem.

## 5. Streaming zdarzeń

Proponowany format zdarzeń:

```json
{"type":"run_started","run_id":"...","thread_id":"..."}
{"type":"delta","text":"Pierwszy fragment"}
{"type":"progress","agent":"database","message":"Searching collection"}
{"type":"approval_required","interrupt_id":"...","value":{"tool":"write_file","arguments":{}}}
{"type":"clarification_required","interrupt_id":"...","question":"Który plik mam wybrać?"}
{"type":"result","status":"completed","answer":"...","evidence":[],"errors":[]}
```

Minimalny zestaw typów:

- `run_started`;
- `delta`;
- `progress`;
- `approval_required`;
- `clarification_required`;
- `run_stopped`;
- `result`;
- `error`;
- `heartbeat`.

Każde zdarzenie powinno zawierać `event_id` i `request_id`. Renderer może wykryć zerwanie połączenia, ale backend pozostaje właścicielem stanu wykonania. Rozłączenie Electrona nie może anulować procesu ani powodować utraty checkpointu.

## 6. Zgody i działania wrażliwe

Backend powinien traktować zgodę jako część stanu workflow, a nie jako decyzję UI. UI jedynie wyświetla dane i odsyła decyzję.

Działania wymagające zgody obejmują co najmniej:

- modyfikację lub usunięcie plików;
- wykonanie poleceń shell/Python;
- indeksowanie dokumentów;
- żądania HTTP POST i inne mutacje sieciowe;
- wysyłanie, odpowiadanie i tworzenie draftów Gmail;
- pobieranie załączników i nieznane narzędzia MCP.

Decyzja powinna wskazywać `interrupt_id` i mieć jawny typ:

```json
{
  "decisions": [
    {"type": "approve"}
  ]
}
```

Backend musi sprawdzić, czy decyzja dotyczy aktualnego checkpointu tej samej rozmowy. Renderer nie może samodzielnie wywoływać narzędzia po zatwierdzeniu.

## 7. Mapowanie na obecny kod

Docelowy backend powinien wykorzystywać istniejące komponenty zamiast przenosić ich logikę do Electrona:

| Obecny komponent | Rola w backendzie |
|---|---|
| `AgentOrchestrator` | Fasada lifecycle pojedynczej rozmowy |
| `SupervisorAgent` | Routing i delegowanie do specjalistów |
| `ConversationStore` | SQLite, historia i checkpointer |
| `AgentOrchestratorConfig` | Konfiguracja ścieżek, hosta, portu i timeoutów |
| `AgentConfig` | Model, limity, prompt i ustawienia agenta |
| `backend/agent_chat_ui.py` | Źródło obecnych handlerów API i zdarzeń; UI docelowo zastąpi Electron |
| `GmailMCP` | Opcjonalna integracja narzędzi Gmail przez stdio |

`sqlite_path` pozostaje konfiguracją backendu. Electron nie powinien znać fizycznej ścieżki do bazy; powinien otrzymywać wyłącznie dane zwrócone przez API.

## 8. Persistence i migracje

Backend jest właścicielem następujących danych:

- historii widocznej dla użytkownika;
- checkpointów LangGraph;
- metadanych rozmów;
- lokalnych ustawień aplikacji, jeżeli zostaną dodane;
- danych ChromaDB i indeksów dokumentów.

Dane użytkownika powinny być przechowywane w katalogu platformowym aplikacji, a nie w katalogu instalacji. Lokalizację należy przekazywać konfiguracją, na przykład:

```text
<app-data>/Platon/
├── agent_threads.sqlite3
├── chroma_data/
├── documents/
├── memory/
├── skills/
└── logs/
```

Przy uruchomieniu backend powinien:

1. utworzyć brakujące katalogi;
2. wykonać jawne migracje schematu;
3. zapisać wersję danych;
4. odmówić startu z czytelnym błędem, jeśli migracja jest niebezpieczna lub nieobsługiwana.

Nie wolno usuwać SQLite ani checkpointów automatycznie przy aktualizacji aplikacji.

## 9. Bezpieczeństwo

### 9.1. Transport lokalny

- nasłuchiwanie wyłącznie na `127.0.0.1`;
- losowy port zamiast stałego portu, jeśli Electron nie wymaga stałego endpointu;
- token sesyjny wymagany w każdym żądaniu API;
- odrzucanie żądań bez poprawnego `Origin`/tokenu, zależnie od użytego transportu;
- limity rozmiaru body i timeouty dla wszystkich endpointów;
- brak wystawiania backendu na `0.0.0.0` bez osobnej decyzji projektowej.

### 9.2. Sekrety

- tokeny OAuth i dane Gmaila pozostają w magazynie obsługiwanym przez MCP lub systemowym secret store;
- `.env`, tokeny, cookies i pliki credential nie mogą trafiać do repozytorium ani logów;
- endpoint diagnostyczny redaguje ścieżki, nagłówki i wartości środowiskowe;
- logi nie powinny zawierać pełnej treści emaili, tokenów ani danych dokumentów;
- import konfiguracji musi jawnie rozdzielać dane publiczne od sekretów.

### 9.3. Izolacja Electrona

Renderer powinien komunikować się wyłącznie przez metody `preload`, np.:

```ts
window.platon.chat.send(threadId, content)
window.platon.chat.onEvent(callback)
window.platon.chat.resume(threadId, interruptId, decision)
```

Nie należy wystawiać ogólnego `window.api.request(url, options)`, ponieważ utrudnia to kontrolę endpointów i zakresu danych.

## 10. Lifecycle i błędy

Backend powinien obsłużyć następujące scenariusze:

- Ollama niedostępna — `503` z kodem `ollama_unavailable`;
- MCP/Gmail niedostępny — jawny błąd integracji, bez pustego sukcesu;
- zerwane połączenie klienta — run może być kontynuowany i widoczny po ponownym połączeniu;
- żądanie zatrzymania — zapis statusu `stopped` i bezpieczne zamknięcie aktywnego strumienia;
- niepewny efekt mutacji — brak automatycznego ponowienia;
- zamykanie aplikacji — kontrolowane zamknięcie agenta, MCP, SQLite i procesu backendu;
- drugi klient — odrzucenie lub jawne ograniczenie, jeśli aplikacja ma być single-user.

Błędy muszą mieć stabilne kody maszynowe. Nie należy maskować wyjątku jako pustej odpowiedzi agenta.

## 11. Proponowany podział modułów

```text
src/platon/backend/
├── server.py              # lifecycle procesu i uruchomienie aiohttp
├── app.py                 # utworzenie aplikacji i middleware
├── auth.py                # token lokalnej sesji
├── health.py              # live/ready/details
├── routes/
│   ├── conversations.py   # rozmowy, wiadomości i resume
│   ├── approvals.py       # zgody i pytania
│   └── system.py          # konfiguracja i status
├── streaming.py           # NDJSON/SSE adapter
├── errors.py              # mapowanie wyjątków na API
└── electron_protocol.py   # wersja kontraktu dla klienta desktopowego
```

To jest warstwa transportowa. Agentów, RAG i persistence nie należy kopiować do `routes`; route powinien walidować żądanie, wywołać istniejący serwis i przetłumaczyć wynik na kontrakt API.

## 12. Kolejność implementacji

### Etap 1 — wydzielenie serwera

- przenieść wspólne tworzenie `AgentOrchestrator` do fabryki backendu;
- dodać osobny launcher procesu;
- wydzielić health endpointy;
- zachować zgodność obecnego web UI.

### Etap 2 — stabilny kontrakt rozmów

- zdefiniować modele request/response;
- ujednolicić kody błędów;
- dodać `request_id`, `run_id` i `event_id`;
- przetestować reconnect i odczyt stanu po restarcie Electrona.

### Etap 3 — aplikacja Electron

- Electron main uruchamia backend;
- preload wystawia wąski typed bridge;
- renderer renderuje stream, progress, approval i clarification;
- zamykanie okna zatrzymuje backend bez kasowania danych.

### Etap 4 — hardening

- testy procesu i lifecycle;
- testy bezpieczeństwa tokenu i izolacji renderer/main;
- testy migracji SQLite;
- testy zerwania połączenia podczas tool call;
- testy pakowania na Windows, macOS i Linux.

## 13. Kryteria akceptacji

Backend jest gotowy do użycia przez Electrona, gdy:

- Electron może wystartować go bez ręcznego uruchamiania terminala;
- renderer nie ma dostępu do Node.js, SQLite ani sekretów;
- rozmowa może być streamowana i wznowiona po utracie połączenia;
- approval i clarification są obsługiwane bez logiki biznesowej w rendererze;
- restart Electrona nie usuwa historii ani checkpointów;
- błędy Ollamy, MCP i narzędzi są widoczne jako jawne błędy;
- API ma wersję i testy kontraktowe;
- backend nasłuchuje wyłącznie lokalnie i wymaga tokenu sesyjnego;
- `uv run --locked python -m unittest discover -s tests -t . -v` pozostaje zielone dla istniejącego backendu;
- klient Electron może wykonać smoke test: start → health → nowa rozmowa → stream → approval → resume → stop → graceful shutdown.

## 14. Decyzje poza zakresem tego dokumentu

- wybór frameworka UI w rendererze;
- wybór biblioteki TypeScript do klienta HTTP;
- automatyczne aktualizacje aplikacji;
- synchronizacja danych między urządzeniami;
- wieloużytkownikowe konta i zdalny serwer;
- wystawienie backendu poza localhost;
- gwarancja exactly-once dla zewnętrznych mutacji.
