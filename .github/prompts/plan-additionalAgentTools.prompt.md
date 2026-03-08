# Plan: Dodatkowe narzędzia dla agenta RAG

## Kontekst

- Agent LangGraph ReAct z ChromaDB (kolekcje + SentenceTransformer `all-MiniLM-L6-v2`)
- `CollectionStore.add_document()` już istnieje (PDF/DOCX/TXT)
- Aktualnie zarejestrowane narzędzia: `search_collection`, `search_all_collections`, `search_web`, `get_list_of_collections`

---

## Proponowane narzędzia

### Faza 1 — Zarządzanie kolekcjami *(code już istnieje w `CollectionStore`/`ClientManager`)*

1. **`add_document_to_collection(collection_name, file_path, doc_name)`**
   Dodaje PDF/DOCX/TXT do kolekcji w locie. Bezpośrednio wywołuje `cm.get_collection(name).add_document()`.

2. **`list_documents_in_collection(collection_name)`**
   Zwraca listę unikalnych nazw dokumentów z metadanych (`collection.get(include=["metadatas"])`). Agent może sprawdzić CO jest w kolekcji zanim zacznie szukać.

3. **`get_collection_stats(collection_name)`**
   Zwraca liczbę chunków w kolekcji via `collection.count()`. Przydatne do diagnozy (np. "czy kolekcja jest pusta?").

4. **`delete_collection(collection_name)`**
   Usuwa kolekcję via `cm.client.delete_collection(name)`. Docstring musi informować agenta, że operacja jest **nieodwracalna**.

### Faza 2 — Utility

5. **`get_current_datetime()`**
   Zwraca aktualną datę i godzinę. Krytyczne dla zapytań o "najnowsze" zdarzenia — agent nie wie który rok/dzień mamy.

6. **`calculator(expression: str)`**
   Bezpieczna ewaluacja wyrażeń matematycznych przez `ast`, **nie** `eval()`. Przydatne gdy agent przetwarza dane liczbowe z dokumentów.

---

## Pliki do modyfikacji

- `agents_tools.py` — główne miejsce, dodać w `create_search_tools()` lub osobna funkcja `create_utility_tools()`
- `client_manager.py` — dodać `delete_collection()` i `get_stats(collection_name)`
- `agent.py` — zarejestrować nowe tools w liście

---

## Otwarte pytania / Decyzje

1. Czy `delete_collection` ma być dostępne dla agenta, czy tylko jako narzędzie administracyjne (poza agentem)? — ryzyko, że agent przypadkowo usunie dane.
2. `add_document_to_collection` — czy agent powinien móc podać dowolną ścieżkę do pliku? Ryzyko: path traversal. Może ograniczyć do katalogu `data/`?
3. `calculator` — wystarczy prosty `ast`-based eval czy potrzebny pełny `numexpr` z obsługą tablic?
