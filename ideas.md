
• Tak, ale nie zawsze wszystkie muszą dziedziczyć
  bezpośrednio po BaseAgent.

  Najzdrowszy układ jest taki:

  - BaseAgent jako wspólna baza techniczna
  - MainAgent, ResearchAgent, CodingAgent, DatabaseAgent
    dziedziczą po BaseAgent

  - tool wrappery typu delegate_research już nie
    dziedziczą po BaseAgent, bo to nie są agenci, tylko
    adaptery


    orchestarot


• Zamiast InMemorySaver możesz użyć:

  - SqliteSaver / AsyncSqliteSaver: stan LangGraph
    zapisuje do pliku SQLite. Dobre lokalnie lub
    dla jednej instancji aplikacji.

  - PostgresSaver / AsyncPostgresSaver: stan
    zapisuje do PostgreSQL. Lepsze na produkcji,
    przy wielu użytkownikach i wielu instancjach
    backendu.

  W Twoim przypadku najbliższy zamiennik to
  SqliteSaver.


  DOKONCZYC ZEBY SZLO BASE AGENT I Z TEGO ROZNE AGENTY PRZEKAZYWNAIE KONFIGOW I DELEFACJA JAKO TOOLE POZNIEJ

  ULEPSZYC RAG I TOOLE 

  faster-whisper
  sdlx
  animatediff?

  piper

  
  Pythonowy odpowiednik udostępnia DuckDuckGoSearchResults z formatami string, json i list: LangChain Python Reference
  (https://reference.langchain.com/python/langchain-community/tools/ddg_search/tool/DuckDuckGoSearchResults).


› wytlumacz mi argumenty w duck duck go seearch resutls i api wrapper


• Sprawdzę aktualne sygnatury obu klas w dokumentacji Pythona, żeby rozdzielić argumenty samego toola od konfiguracji wrappera API.

◦ Searching the web

• Searched the web for site:reference.langchain.com/python/langchain-community DuckDuckGoSearchResults max_results output_format keys_to_include backend ...

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

• Najważniejsze rozróżnienie:

  - DuckDuckGoSearchAPIWrapper wykonuje właściwe wyszukiwanie i ustala co oraz jak wyszukujemy.
  - DuckDuckGoSearchResults jest narzędziem LangChain dla agenta i ustala głównie jak wynik zostanie zwrócony agentowi.

  ## DuckDuckGoSearchAPIWrapper

  from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

  wrapper = DuckDuckGoSearchAPIWrapper(
      region="pl-pl",
      safesearch="moderate",
      time="m",
      max_results=10,
      backend="auto",
      source="text",
  )

  ### region

  Region i język wyników:

  region="pl-pl"
  region="us-en"
  region="de-de"
  region="wt-wt"  # brak konkretnego regionu

  Wpływa na język, lokalizację i kolejność wyników. Nie jest twardym filtrem, więc pl-pl nie gwarantuje wyłącznie polskich stron.

  ### safesearch

  Filtrowanie treści dla dorosłych:

  safesearch="strict"
  safesearch="moderate"  # domyślne
  safesearch="off"

  Dla agenta używanego przez klientów zostawiłbym moderate albo strict.

  ### time

  Ograniczenie wieku wyników:

  time="d"     # ostatni dzień
  time="w"     # ostatni tydzień
  time="m"     # ostatni miesiąc
  time="y"     # ostatni rok
  time=None    # bez ograniczenia

  Przydatne dla aktualności. Dla pytań ogólnych lepiej None, ponieważ filtr może mocno pogorszyć wyniki.

  ### max_results

  Maksymalna liczba wyników zwracanych przez wrapper:

  max_results=10

  Jeśli później robisz reranking, pobieraj więcej kandydatów:

  max_results=15

  Następnie reranker może wybrać najlepsze 3–5.

  ### backend

  Mechanizm używany przez bibliotekę do pozyskania wyników:

  backend="auto"
  backend="html"
  backend="lite"

  - auto – biblioteka sama wybiera sposób; najlepszy domyślny wariant.
  - html – korzysta z HTML-owej wersji wyszukiwarki.
  - lite – używa uproszczonej wersji DuckDuckGo.

  Zacząłbym od:

  backend="auto"

  html lub lite traktowałbym jako fallback, jeśli auto daje błędy albo niestabilne wyniki.

  ### source

  Typ wyszukiwania:

  source="text"
  source="news"
  source="images"

  - text – zwykłe strony internetowe.
  - news – wiadomości.
  - images – grafiki.

  Dla standardowego agenta:

  source="text"

  ### Metody wrappera

  Wrapper ma dwa główne sposoby wywołania:

  text = wrapper.run("LangGraph tutorial")

  run() zwraca połączony tekst. Jest wygodny dla prostego promptu, ale słaby do rerankingu.

  results = wrapper.results(
      query="LangGraph tutorial",
      max_results=10,
  )

  results() zwraca listę słowników z metadanymi. To lepsza forma do filtrowania, linkowania i rerankingu. Dokumentacja wrappera
  (https://reference.langchain.com/python/langchain-community/utilities/duckduckgo_search/DuckDuckGoSearchAPIWrapper)

  ## DuckDuckGoSearchResults

  from langchain_community.tools import DuckDuckGoSearchResults

  search_tool = DuckDuckGoSearchResults(
      api_wrapper=wrapper,
      num_results=10,
      backend="text",
      keys_to_include=["title", "snippet", "link"],
      output_format="list",
  )

  Tu jest istotna pułapka: backend w toolu i backend we wrapperze nie oznaczają dokładnie tego samego.

  ### api_wrapper

  Wrapper, którego tool ma używać:

  api_wrapper=wrapper

  Dzięki temu konfigurujesz region, SafeSearch, czas i techniczny backend w jednym miejscu.

  Jeżeli go nie przekażesz, tool utworzy własny wrapper z ustawieniami domyślnymi.

  ### num_results / max_results

  W DuckDuckGoSearchResults pole ma nazwę max_results, ale jego alias konstruktora to num_results; domyślnie wynosi 4. Dokumentacja max_results
  (https://reference.langchain.com/python/langchain-community/tools/ddg_search/tool/DuckDuckGoSearchResults/max_results)

  Najbezpieczniej pisać:

  num_results=10

  To liczba wyników, które tool chce zwrócić agentowi.

  Jeśli konfigurujesz również wrapper, warto zachować tę samą wartość:

  wrapper = DuckDuckGoSearchAPIWrapper(max_results=10)

  tool = DuckDuckGoSearchResults(
      api_wrapper=wrapper,
      num_results=10,
  )

  ### backend w DuckDuckGoSearchResults

  W tej klasie backend oznacza rodzaj wyszukiwania:

  backend="text"
  backend="news"

  Nie należy mylić go z:

  DuckDuckGoSearchAPIWrapper(backend="auto")

  Czyli:

  wrapper = DuckDuckGoSearchAPIWrapper(
      backend="auto",  # techniczna metoda pobrania
  )

  tool = DuckDuckGoSearchResults(
      api_wrapper=wrapper,
      backend="text",  # rodzaj wyszukiwania
  )

  Nazewnictwo jest niestety niespójne. Wrapper ma również pole source, które reprezentuje typ wyszukiwania.

  ### keys_to_include

  Określa, które pola zachować:

  keys_to_include=["title", "snippet", "link"]

  Bez tego:

  keys_to_include=None

  tool zwróci wszystkie dostępne pola.

  Do agenta tekstowego podałbym tylko:

  ["title", "snippet", "link"]

  Zmniejsza to liczbę tokenów i zachowuje dane potrzebne do cytowania.

  Dla news mogą pojawić się dodatkowe pola, na przykład data lub źródło.

  ### results_separator

  Separator pomiędzy wynikami, używany głównie przy formacie tekstowym:

  results_separator="\n\n"

  Nie ma większego znaczenia, jeżeli wybierzesz:

  output_format="list"

  ### output_format

  Format odpowiedzi toola:

  output_format="string"
  output_format="json"
  output_format="list"

  - string – wyniki połączone w jeden tekst.
  - json – wyniki jako tekst zawierający JSON.
  - list – rzeczywista list[dict].

  Do własnego rerankingu:

  output_format="list"

  Do prostego agenta można użyć string, ale tracisz wygodną pracę na polach. Dostępne formaty potwierdza dokumentacja output_format
  (https://reference.langchain.com/python/langchain-community/tools/ddg_search/tool/DuckDuckGoSearchResults/output_format).

  ### name i description

  To standardowe pola BaseTool:

  name="duckduckgo_results_json"
  description="Search DuckDuckGo for current public web information."

  - name identyfikuje tool.
  - description mówi modelowi, kiedy powinien go wywołać.

  Opis jest ważny, ponieważ agent podejmuje na jego podstawie decyzję o użyciu narzędzia.

  ### Pozostałe argumenty BaseTool

  Klasa dziedziczy też ogólne opcje LangChain:

  - return_direct – rezultat toola kończy pracę agenta i trafia bezpośrednio do użytkownika.
  - verbose – dodatkowe logowanie.
  - tags – tagi do trace’ów.
  - metadata – własne metadane trace’a.
  - callbacks – callbacki LangChain.
  - handle_tool_error – sposób obsługi błędów wykonania.
  - handle_validation_error – obsługa błędnych argumentów wejściowych.

  Zwykle nie musisz ich ustawiać.

  ## Polecana konfiguracja

  wrapper = DuckDuckGoSearchAPIWrapper(
      region="pl-pl",
      safesearch="moderate",
      time=None,
      max_results=12,
      backend="auto",
      source="text",
  )

  search_tool = DuckDuckGoSearchResults(
      api_wrapper=wrapper,
      num_results=12,
      backend="text",
      keys_to_include=["title", "snippet", "link"],
      output_format="list",
  )

  Dla Twojego pipeline’u pobrałbym 12 wyników, usunął duplikaty URL, zrobił reranking i zwrócił agentowi najlepsze 4–5.

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


› jeszce raz mi  wytlumacz rankingowanie i deduplikacje w kodzie snippety rowniez, cos wiecje jeszcze ?


• Najprostszy sensowny pipeline:

  DuckDuckGo: 15 wyników
  → normalizacja danych
  → deduplikacja
  → ranking podobieństwa
  → opcjonalny reranking przez LLM
  → najlepsze 3–5 wyników dla agenta

  ## 1. Normalizacja

  DuckDuckGo może zwracać różne nazwy pól zależnie od źródła i wersji:

  def normalize_result(result: dict) -> dict:
      return {
          "title": result.get("title", "").strip(),
          "url": (
              result.get("link")
              or result.get("url")
              or result.get("href")
              or ""
          ).strip(),
          "snippet": (
              result.get("snippet")
              or result.get("body")
              or result.get("description")
              or ""
          ).strip(),
      }

  Dla całej listy:

  normalized = [
      normalize_result(result)
      for result in raw_results
  ]

  Warto odrzucić wyniki bez URL-a lub treści:

  normalized = [
      result
      for result in normalized
      if result["url"] and (result["title"] or result["snippet"])
  ]

  ## 2. Deduplikacja URL

  Ta sama strona może występować jako:

  https://example.com/article
  https://example.com/article/
  https://example.com/article?utm_source=google
  https://www.example.com/article#section

  Logicznie jest to jeden dokument. Najpierw tworzymy kanoniczną wersję URL-a.

  from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

  TRACKING_PARAMS = {
      "utm_source",
      "utm_medium",
      "utm_campaign",
      "utm_term",
      "utm_content",
      "fbclid",
      "gclid",
  }

  def canonicalize_url(url: str) -> str:
      parsed = urlsplit(url)

      host = parsed.netloc.lower()
      if host.startswith("www."):
          host = host[4:]

      path = parsed.path.rstrip("/") or "/"

      query_params = [
          (key, value)
          for key, value in parse_qsl(parsed.query, keep_blank_values=True)
          if key.lower() not in TRACKING_PARAMS
      ]

      query_params.sort()

      return urlunsplit((
          parsed.scheme.lower() or "https",
          host,
          path,
          urlencode(query_params),
          "",  # usunięcie fragmentu #section
      ))

  Deduplikacja:

  def deduplicate_by_url(results: list[dict]) -> list[dict]:
      seen = set()
      unique = []

      for result in results:
          canonical_url = canonicalize_url(result["url"])

          if canonical_url in seen:
              continue

          seen.add(canonical_url)

          unique.append({
              **result,
              "canonical_url": canonical_url,
          })

      return unique

  Użycie:

  unique_results = deduplicate_by_url(normalized)

  Zachowujemy pierwszy wynik, ponieważ DuckDuckGo zwykle zwraca wyniki w kolejności trafności.

  ## 3. Deduplikacja treści

  Dwa różne URL-e mogą zawierać ten sam artykuł:

  example.com/news/article
  example.com/mobile/news/article
  partner.com/reprint/article

  Można wykryć proste duplikaty przez znormalizowany tytuł i snippet:

  import re


  def normalize_text(text: str) -> str:
      text = text.lower()
      text = re.sub(r"\s+", " ", text)
      text = re.sub(r"[^\w\s]", "", text)
      return text.strip()

  def deduplicate_by_content(results: list[dict]) -> list[dict]:
      seen = set()
      unique = []

      for result in results:
          fingerprint = normalize_text(
              f"{result['title']} {result['snippet']}"
          )

          if fingerprint in seen:
              continue

          seen.add(fingerprint)
          unique.append(result)

      return unique

  To wykrywa tylko identyczną lub prawie identycznie zapisaną treść. Nie wykryje dobrze parafraz.

  ## 4. Deduplikacja semantyczna

  Można też porównać embeddingi wyników. Jeżeli similarity dwóch wyników przekracza np. 0.96, uznajemy je za duplikaty.

  import numpy as np


  def cosine_similarity(a: list[float], b: list[float]) -> float:
      a = np.asarray(a, dtype=float)
      b = np.asarray(b, dtype=float)

      denominator = np.linalg.norm(a) * np.linalg.norm(b)

      if denominator == 0:
          return 0.0

      return float(np.dot(a, b) / denominator)

  def semantic_deduplicate(
      results: list[dict],
      vectors: list[list[float]],
      threshold: float = 0.96,
  ) -> tuple[list[dict], list[list[float]]]:
      unique_results = []
      unique_vectors = []

      for result, vector in zip(results, vectors):
          is_duplicate = any(
              cosine_similarity(vector, existing_vector) >= threshold
              for existing_vector in unique_vectors
          )

          if is_duplicate:
              continue

          unique_results.append(result)
          unique_vectors.append(vector)

      return unique_results, unique_vectors

  Próg:

  - 0.99 – usuwa praktycznie identyczne treści.
  - 0.96 – rozsądny początek dla duplikatów.
  - 0.90 – może już usuwać różne dokumenty dotyczące tego samego tematu.

  Nie zaczynałbym od deduplikacji semantycznej. Dla 10–20 wyników często wystarczy URL oraz fingerprint treści.

  ## 5. Ranking embeddingami

  Ranking odpowiada na pytanie:

  > Który wynik jest semantycznie najbardziej podobny do zapytania użytkownika?

  Najpierw tworzymy tekst reprezentujący wynik:

  def result_to_text(result: dict) -> str:
      return (
          f"Title: {result['title']}\n"
          f"Content: {result['snippet']}"
      )

  Embedding zapytania i wyników:

  from langchain_openai import OpenAIEmbeddings

  embeddings = OpenAIEmbeddings(
      model="text-embedding-3-small",
  )

  query = "Jak zrobić reranking wyników wyszukiwania w LangChain?"

  document_texts = [
      result_to_text(result)
      for result in unique_results
  ]

  query_vector = embeddings.embed_query(query)
  document_vectors = embeddings.embed_documents(document_texts)

  Następnie liczymy similarity:

  ranked_results = []

  for position, (result, vector) in enumerate(
      zip(unique_results, document_vectors)
  ):
      similarity = cosine_similarity(query_vector, vector)

      ranked_results.append({
          **result,
          "similarity_score": similarity,
          "original_position": position,
      })

  Sortowanie:

  ranked_results.sort(
      key=lambda result: result["similarity_score"],
      reverse=True,
  )

  top_results = ranked_results[:5]

  Przykładowy rezultat:

  [
      {
          "title": "Reranking in LangChain",
          "url": "https://example.com/reranking",
          "similarity_score": 0.84,
          "original_position": 3,
      },
      {
          "title": "Vector search tutorial",
          "url": "https://example.com/vector-search",
          "similarity_score": 0.77,
          "original_position": 0,
      },
  ]

  similarity_score nie jest prawdopodobieństwem. Wynik 0.84 nie oznacza „84% pewności”. Służy głównie do porównania dokumentów między sobą.

  ## 6. Ranking hybrydowy

  Nie ignorowałbym całkowicie rankingu DuckDuckGo. Pierwszy wynik DDG może być dobry ze względu na autorytet strony, dopasowanie słów i inne sygnały,
  których embedding nie zna.

  Można połączyć:

  - similarity embeddingu,
  - pozycję z DuckDuckGo.

  def position_score(position: int) -> float:
      return 1.0 / (position + 1)

  for position, (result, vector) in enumerate(
      zip(unique_results, document_vectors)
  ):
      similarity = cosine_similarity(query_vector, vector)
      ddg_score = position_score(position)

      final_score = (
          0.8 * similarity
          + 0.2 * ddg_score
      )

      ranked_results.append({
          **result,
          "similarity_score": similarity,
          "ddg_score": ddg_score,
          "final_score": final_score,
      })

  Sortowanie:

  ranked_results.sort(
      key=lambda result: result["final_score"],
      reverse=True,
  )

  Na początek użyłbym:

  80% embedding similarity
  20% pozycja DuckDuckGo

  Potem warto dobrać wagi eksperymentalnie.

  ## 7. Ograniczenie liczby wyników z jednej domeny

  Bez tego top 5 może wyglądać tak:

  docs.example.com/page-1
  docs.example.com/page-2
  docs.example.com/page-3
  docs.example.com/page-4
  other.com/page

  Agent dostaje wtedy mało różnorodne źródła.

  from collections import defaultdict
  from urllib.parse import urlsplit


  def limit_results_per_domain(
      results: list[dict],
      per_domain: int = 2,
      limit: int = 5,
  ) -> list[dict]:
      counts = defaultdict(int)
      selected = []

      for result in results:
          domain = urlsplit(result["url"]).netloc.lower()

          if counts[domain] >= per_domain:
              continue

          counts[domain] += 1
          selected.append(result)

          if len(selected) >= limit:
              break

      return selected

  Użycie:

  final_results = limit_results_per_domain(
      ranked_results,
      per_domain=2,
      limit=5,
  )

  ## 8. Cały mały pipeline

  def prepare_search_results(
      query: str,
      raw_results: list[dict],
      limit: int = 5,
  ) -> list[dict]:
      results = [normalize_result(item) for item in raw_results]

      results = [
          item
          for item in results
          if item["url"] and (item["title"] or item["snippet"])
      ]

      results = deduplicate_by_url(results)
      results = deduplicate_by_content(results)

      texts = [result_to_text(item) for item in results]

      query_vector = embeddings.embed_query(query)
      document_vectors = embeddings.embed_documents(texts)

      ranked = []

      for position, (result, vector) in enumerate(
          zip(results, document_vectors)
      ):
          similarity = cosine_similarity(query_vector, vector)
          ddg_score = position_score(position)

          ranked.append({
              **result,
              "score": 0.8 * similarity + 0.2 * ddg_score,
          })

      ranked.sort(key=lambda item: item["score"], reverse=True)

      return limit_results_per_domain(
          ranked,
          per_domain=2,
          limit=limit,
      )

  Połączenie z DuckDuckGo:

  raw_results = search_tool.invoke(query)

  final_results = prepare_search_results(
      query=query,
      raw_results=raw_results,
      limit=5,
  )

  ## 9. Czy snippet wystarczy?

  Snippet DuckDuckGo jest krótki i czasem nie reprezentuje dobrze strony. Dokładniejszy pipeline wygląda tak:

  wyszukaj 15 wyników
  → deduplikuj
  → embeddingami wybierz 8
  → pobierz treść tych 8 stron
  → podziel strony na fragmenty
  → ponownie oceń fragmenty
  → zwróć najlepsze 4 źródła

  Nie pobierałbym zawartości wszystkich stron od razu, ponieważ zwiększa to czas, koszty i ryzyko błędów.

  ## 10. Opcjonalny reranking przez LLM

  Embedding ocenia podobieństwo tematyczne. Nie zawsze ocenia, czy dokument rzeczywiście odpowiada na pytanie.

  Przykład:

  Zapytanie: Jak skonfigurować timeout DuckDuckGoSearchResults?

  Wynik A: ogólny artykuł o DuckDuckGo
  Wynik B: dokumentacja dokładnie opisująca timeout

  Oba mogą być podobne semantycznie, ale wynik B jest bardziej użyteczny. Dlatego można przekazać top 8 do LLM-a:

  from pydantic import BaseModel, Field


  class RerankingResult(BaseModel):
      indices: list[int] = Field(
          description="Indices ordered from most to least relevant"
      )

  reranker = model.with_structured_output(RerankingResult)

  formatted = "\n\n".join(
      f"[{index}] {result['title']}\n{result['snippet']}"
      for index, result in enumerate(ranked_results[:8])
  )

  ranking = reranker.invoke(
      f"""
      User query:
      {query}

      Search results:
      {formatted}
  )

  llm_ranked = [
      ranked_results[index]
  ]

  ## Rekomendowany wariant

  Na początek nie komplikowałbym tego nadmiernie:

  15 wyników DuckDuckGo
  → deduplikacja URL
  → deduplikacja identycznej treści
  → 80% similarity + 20% pozycja DDG
  → maksymalnie 2 wyniki na domenę
  → top 5

  LLM reranker dodałbym dopiero wtedy, gdy testy pokażą, że embeddingi często wybierają wyniki związane z tematem, ale nieodpowiadające bezpośrednio na
  pytanie.


› krotko odpowiedz czy warto reranking llm jesli potem to idzie do agenta?


• Zwykle nie na początku. Agent sam oceni wyniki, więc dodatkowy reranking LLM zwiększa koszt i opóźnienie.

  Wystarczy:

  DDG top 10–15 → deduplikacja → embedding similarity → top 5 → agent

  LLM reranker warto dodać dopiero, gdy wyniki są często podobne tematycznie, ale nie odpowiadają bezpośrednio na pytanie, albo gdy koszt przekazania wielu
  wyników do agenta jest wysoki.


› @lru_cache(maxsize=1)
  def get_model():
      """Get the global SentenceTransformer model."""
      model = SentenceTransformer("all-MiniLM-L6-v2")
      return model
  a tne model git?


• Technicznie git, a @lru_cache(maxsize=1) poprawnie ładuje model tylko raz na proces.

  Ale all-MiniLM-L6-v2 najlepiej działa po angielsku. Dla polskich zapytań wybrałbym:

  SentenceTransformer("intfloat/multilingual-e5-small")

  Przy E5 używaj prefiksów:

  query = f"query: {query}"
  documents = [f"passage: {text}" for text in documents]

  Jeśli wyszukiwanie jest głównie angielskie, all-MiniLM-L6-v2