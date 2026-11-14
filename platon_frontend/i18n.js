const STORAGE_KEY = "platon.language";
const UI_STRINGS = {
  "Wczytuję obrazy…": "Loading images…",
  "Galeria odświeży się po zakończeniu zadania.": "The gallery will refresh when the task finishes.",
  "Nie udało się wczytać galerii. Kliknij Odśwież.": "Could not load the gallery. Click Refresh.",
  "Nie udało się wczytać obrazu. Kliknij Odśwież.": "Could not load the image. Click Refresh.",
  "Nawigacja rozmów": "Conversation navigation",
  "Platon — strona główna": "Platon — home",
  "Platon.ai — strona główna": "Platon.ai — home",
  "Zwiń panel": "Collapse sidebar",
  "Zwiń panel (Ctrl+B)": "Collapse sidebar (Ctrl+B)",
  "Rozwiń panel": "Expand sidebar",
  "Rozwiń panel (Ctrl+B)": "Expand sidebar (Ctrl+B)",
  "Nowa rozmowa": "New chat",
  "Szukaj w rozmowach…": "Search conversations…",
  "Szukaj w rozmowach": "Search conversations",
  "Twoje rozmowy": "Your conversations",
  "Odśwież rozmowy": "Refresh conversations",
  "Odśwież": "Refresh",
  "Lista rozmów": "Conversation list",
  "Dokumenty": "Documents",
  "Wygenerowane obrazy": "Generated images",
  "Ustawienia": "Settings",
  "Status połączenia z backendem": "Backend connection status",
  "Łączenie z backendem…": "Connecting to backend…",
  "Otwórz nawigację": "Open navigation",
  "PRACOWNIA ROZMÓW": "CONVERSATION STUDIO",
  "Agent lokalny": "Local agent",
  "Przełącz motyw": "Toggle theme",
  "Zmień motyw (Jasny / Ciemny)": "Change theme (Light / Dark)",
  "Eksportuj rozmowę": "Export conversation",
  "Eksportuj rozmowę do Markdown": "Export conversation to Markdown",
  "Opcje rozmowy": "Conversation options",
  "Usuń rozmowę": "Delete conversation",
  "Minimalizuj": "Minimize",
  "Maksymalizuj": "Maximize",
  "Zamknij": "Close",
  "Otwórz": "Open",
  "Wiadomości": "Messages",
  "Przewiń na dół": "Scroll to bottom",
  "Wiadomość": "Message",
  "Napisz, nad czym dziś pracujemy…": "What are we working on today…",
  "Wybierz dokumenty do RAG": "Choose documents for RAG",
  "Źródła RAG": "RAG sources",
  "Zatrzymaj": "Stop",
  "Porzuć niedokończone": "Discard unfinished run",
  "Wznów": "Resume",
  "Wyślij wiadomość": "Send message",
  "Wyślij": "Send",
  "Platon może się mylić. Sprawdzaj ważne informacje.": "Platon can make mistakes. Check important information.",
  "KONFIGURACJA": "CONFIGURATION",
  "Ustawienia agenta": "Agent settings",
  "Połączenie lokalne, wygląd i parametry nowego przebiegu.": "Local connection, appearance, and settings for the next run.",
  "Motyw interfejsu": "Interface theme",
  "Systemowy": "System",
  "Jasny": "Light",
  "Ciemny": "Dark",
  "Zmiany zastąpią aktywny runtime.": "Changes will replace the active runtime.",
  "Zapisz ustawienia": "Save settings",
  "BAZA WIEDZY": "KNOWLEDGE BASE",
  "Wybierz kolekcję i dokumenty, które agent ma przeszukać przez RAG.": "Choose a collection and documents for the agent to search with RAG.",
  "Wybierz plik do indeksowania": "Choose a file to index",
  "PDF, DOCX lub TXT · maks. 100 MB": "PDF, DOCX, or TXT · max 100 MB",
  "Kolekcja": "Collection",
  "Nowa kolekcja…": "New collection…",
  "Dodaj dokument": "Add document",
  "Nazwa nowej kolekcji": "New collection name",
  "np. matematyka": "e.g. mathematics",
  "Wszystkie kolekcje": "All collections",
  "Filtruj dokumenty po nazwie lub kolekcji…": "Filter documents by name or collection…",
  "Filtruj dokumenty": "Filter documents",
  "ZAINDEKSOWANE DOKUMENTY": "INDEXED DOCUMENTS",
  "0 wybranych": "0 selected",
  "Użyj w RAG": "Use in RAG",
  "GALERIA": "GALLERY",
  "Podgląd obrazów utworzonych w rozmowach.": "Preview images created in conversations.",
  "Filtruj obrazy po nazwie pliku…": "Filter images by filename…",
  "Filtruj obrazy": "Filter images",
  "Adres Ollama": "Ollama URL",
  "Katalog kolekcji Chroma": "Chroma collection directory",
  "Katalog roboczy": "Working directory",
  "Ścieżka bazy SQLite (opcjonalnie)": "SQLite database path (optional)",
  "Model Ollama": "Ollama model",
  "Temperatura": "Temperature",
  "Plik promptu systemowego": "System prompt file",
  "Liczba wiadomości w kontekście": "Messages in context",
  "Limit znaków wyniku narzędzia": "Tool output character limit",
  "Czas utrzymania modelu": "Model keep-alive",
  "Okno kontekstu modelu": "Model context window",
  "Włącz rozumowanie modelu": "Enable model reasoning",
  "Tryb debugowania": "Debug mode",
  "Limit narzędzi research": "Research tool limit",
  "Limit narzędzi coding": "Coding tool limit",
  "Limit narzędzi database": "Database tool limit",
  "Limit czasu wykonania (s)": "Execution timeout (s)",
  "Katalog danych agenta": "Agent data directory",
  "Ścieżki skills (jedna w wierszu)": "Skill paths (one per line)",
  "Pliki pamięci (jeden w wierszu)": "Memory files (one per line)",
  "Połączenie i pamięć": "Connection and memory",
  "Backend Ollama, workspace i baza historii.": "Ollama backend, workspace, and history database.",
  "Zachowanie agenta": "Agent behavior",
  "Model, kontekst oraz dostępne zasoby.": "Model, context, and available resources.",
  "Domyślnie w katalogu danych agenta": "Defaults to the agent data directory",
  "Odśwież modele": "Refresh models",
  "Wybierz model…": "Choose a model…",
  "Połączone": "Connected",
  "Backend połączony": "Backend connected",
  "Brak połączenia z backendem": "Backend disconnected",
  "Nie udało się połączyć": "Could not connect",
  "Ponawiam połączenie…": "Retrying connection…",
  "Backend zajęty (trwa zadanie)": "Backend busy (task running)",
  "Agent wykonuje zadanie w tle. Możesz je zatrzymać.": "The agent is working in the background. You can stop it.",
  "Agent wykonuje zadanie w tle. Możesz je zatrzymać przyciskiem poniżej.": "The agent is working in the background. You can stop it with the button below.",
  "Brak rozmów pasujących do wyszukiwania.": "No conversations match your search.",
  "Twoje rozmowy pojawią się tutaj.": "Your conversations will appear here.",
  "Rozmowa bez tytułu": "Untitled conversation",
  "bez tytułu": "untitled",
  "Od czego zaczynamy?": "Where shall we start?",
  "LOKALNY ASYSTENT AI": "LOCAL AI ASSISTANT",
  "Porozmawiaj z Platonem o dokumentach, pomysłach albo zadaniu, które masz przed sobą.": "Talk to Platon about documents, ideas, or a task in front of you.",
  "Odnajdź odpowiedź": "Find an answer",
  "Przeszukaj moje dokumenty i wskaż źródła": "Search my documents and cite sources",
  "Uporządkuj pomysł": "Organize an idea",
  "Pomóż mi ułożyć plan na najbliższy tydzień": "Help me plan the coming week",
  "Wyjaśnij temat": "Explain a topic",
  "Wytłumacz mi trudny temat prostymi słowami": "Explain a difficult topic in simple terms",
  "Zanim Platon pójdzie dalej": "Before Platon continues",
  "Doprecyzowanie": "Clarification",
  "Zatwierdź działanie": "Approve action",
  "Wpisz odpowiedź…": "Enter your answer…",
  "Odpowiedź na pytanie agenta": "Answer to the agent's question",
  "Działanie": "Action",
  "Wybierz decyzję": "Choose a decision",
  "Zatwierdź": "Approve",
  "Odrzuć": "Reject",
  "Wznawiam rozmowę…": "Resuming conversation…",
  "Przebieg nie został dokończony.": "The run did not finish.",
  "Nieukończony przebieg": "Unfinished run",
  "Wznów od zapisanego stanu": "Resume from saved state",
  "Przebieg zatrzymany. Dotychczasowa historia została zachowana.": "Run stopped. The conversation history has been preserved.",
  "Odpowiedź gotowa.": "Answer ready.",
  "Brak dokumentów pasujących do wyszukiwania.": "No documents match your search.",
  "Nie ma jeszcze dokumentów. Dodaj TXT, PDF lub DOCX, aby korzystać z nich jako źródeł.": "There are no documents yet. Add a TXT, PDF, or DOCX file to use as a source.",
  "Usuń": "Delete",
  "limit osiągnięty": "limit reached",
  "Zamknij podgląd": "Close preview",
  "Nie udało się wczytać obrazu. Zamknij galerię i otwórz ją ponownie.": "Could not load the image. Close the gallery and open it again.",
  "Brak obrazów pasujących do wyszukiwania.": "No images match your search.",
  "Wygenerowane obrazy pojawią się tutaj.": "Generated images will appear here.",
  "Kopiuj": "Copy",
  "Kopiuj kod": "Copy code",
  "Kopiuj treść odpowiedzi": "Copy answer",
  "Skopiowano!": "Copied!",
  "Nie udało się skopiować kodu do schowka.": "Could not copy code to the clipboard.",
  "Nie udało się skopiować wiadomości.": "Could not copy the message.",
  "Otwieram rozmowę…": "Opening conversation…",
  "Wysyłam sygnał zatrzymania…": "Sending stop signal…",
  "Agent zatrzymuje bieżący przebieg…": "The agent is stopping the current run…",
  "Nie ma aktywnego przebiegu do zatrzymania.": "There is no active run to stop.",
  "Niedokończony przebieg został porzucony.": "The unfinished run was discarded.",
  "Brak wiadomości do wyeksportowania.": "There are no messages to export.",
  "Rozmowa została wyeksportowana do pliku Markdown.": "Conversation exported to a Markdown file.",
  "Zainstaluj model w Ollama i odśwież listę.": "Install a model in Ollama and refresh the list.",
  "Nie udało się skopiować kodu do schowka.": "Could not copy code to the clipboard.",
  "Wystąpił błąd": "An error occurred",
  "Odświeżam stan rozmowy…": "Refreshing conversation state…",
  "Wybrany dokument jest niedostępny. Odśwież bibliotekę i wybierz źródła ponownie.": "The selected document is unavailable. Refresh the library and choose sources again.",
  "Platon układa odpowiedź…": "Platon is preparing an answer…",
  "Indeksuję…": "Indexing…",
  "Zapisuję…": "Saving…",
  "Ustawienia zostały zapisane.": "Settings saved.",
  "Nie udało się skopiować kodu do schowka.": "Could not copy code to the clipboard.",
  "Błąd backendu": "Backend error",
  "Wystąpił nieoczekiwany błąd.": "An unexpected error occurred.",
  "Nazwa kolekcji musi mieć 3–63 znaki: litery, cyfry, _ lub -. Pierwszy i ostatni znak musi być literą lub cyfrą.": "Collection names must be 3–63 characters: letters, digits, _ or -. The first and last characters must be a letter or digit.",
  "Otwieranie plików i folderów jest dostępne w aplikacji desktopowej.": "Opening files and folders is available in the desktop app.",
  "Wygenerowany obraz": "Generated image",
  "Nie udało się wczytać obrazu.": "Could not load the image.",
  "Pobierz": "Download",
  "Agent potrzebuje dodatkowych informacji.": "The agent needs more information.",
  "Informacja zwrotna (opcjonalnie)": "Feedback (optional)",
  "Informacja zwrotna do decyzji": "Feedback for the decision",
  "POTRZEBNA TWOJA DECYZJA": "YOUR DECISION IS NEEDED",
  "Rozmowa pozostanie wstrzymana do czasu odpowiedzi.": "The conversation will remain paused until you respond.",
  "Odpowiedz i kontynuuj": "Respond and continue",
  "Decyzja": "Decision",
  "Oczekuje odpowiedź — formularz znajduje się powyżej.": "Waiting for your response — the form is above.",
  "Przebieg można wznowić od ostatniego zapisanego kroku.": "The run can resume from the last saved step.",
  "Wyczyszczono źródła RAG.": "RAG sources cleared.",
  "Usunąć tę rozmowę i jej zapisane punkty kontrolne?": "Delete this conversation and its saved checkpoints?",
  "Nie udało się skopiować wiadomości.": "Could not copy the message.",
};

const EN_TO_PL = Object.fromEntries(Object.entries(UI_STRINGS).map(([pl, en]) => [en, pl]));
const DYNAMIC_PREFIXES = [
  ["Usuń rozmowę: ", "Delete conversation: "],
  ["Użyj w RAG: ", "Use in RAG: "],
  ["Usuń dokument ", "Delete document "],
  ["Odłącz ", "Detach "],
  ["Otwórz ", "Open "],
  ["Źródło RAG · kolekcja ", "RAG source · collection "],
  ["Nie udało się otworzyć zasobu: ", "Could not open resource: "],
  ["Nie udało się pobrać rozmów: ", "Could not load conversations: "],
  ["Nie udało się pobrać obrazów: ", "Could not load images: "],
  ["Nie udało się uruchomić agenta: ", "Could not start the agent: "],
  ["Nie udało się otworzyć rozmowy: ", "Could not open conversation: "],
  ["Nie udało się usunąć rozmowy: ", "Could not delete conversation: "],
  ["Nie udało się zatrzymać agenta: ", "Could not stop the agent: "],
  ["Nie udało się porzucić przebiegu: ", "Could not discard the run: "],
  ["Nie udało się pobrać modeli: ", "Could not load models: "],
  ["Nie udało się pobrać dokumentów: ", "Could not load documents: "],
  ["Nie udało się usunąć dokumentu: ", "Could not delete document: "],
  ["Nie udało się usunąć obrazu: ", "Could not delete image: "],
  ["Nie udało się dodać dokumentu: ", "Could not add document: "],
  ["Nie udało się utworzyć rozmowy: ", "Could not create conversation: "],
  ["Nie udało się skopiować wiadomości.", "Could not copy the message."],
  ["Przełączono motyw na: ", "Theme changed to: "],
  ["Decyzja: ", "Decision: "],
  ["Konfiguracja domyślna. ", "Default configuration. "],
  ["Stan rozmowy został odświeżony. ", "Conversation state refreshed. "],
  ["Nie udało się odświeżyć historii: ", "Could not refresh history: "],
  ["Błąd backendu (", "Backend error ("],
];

export function translateText(value, language = "en") {
  const text = String(value);
  if (language === "pl") {
    if (EN_TO_PL[text] !== undefined) return EN_TO_PL[text];
    for (const [plPrefix, enPrefix] of DYNAMIC_PREFIXES) {
      if (text.startsWith(enPrefix)) return `${plPrefix}${text.slice(enPrefix.length)}`;
    }
    const selectedCount = text.match(/^(\d+) selected(?: · limit reached)?$/);
    if (selectedCount) return `${selectedCount[1]} wybranych${text.endsWith("limit reached") ? " · limit osiągnięty" : ""}`;
    const modelCount = text.match(/^Available models: (\d+)$/);
    if (modelCount) return `Dostępne modele: ${modelCount[1]}`;
    const addedDocument = text.match(/^Added document “(.*)”\.$/);
    if (addedDocument) return `Dodano dokument „${addedDocument[1]}”.`;
    const selectedRag = text.match(/^Selected RAG sources: (\d+)\.$/);
    if (selectedRag) return `Wybrano źródła RAG: ${selectedRag[1]}.`;
    const deletedDocument = text.match(/^Delete “(.*)” from the directory and collection\?$/);
    if (deletedDocument) return `Usunąć „${deletedDocument[1]}” z katalogu i kolekcji?`;
    const deletedImage = text.match(/^Delete image (.*)\?$/);
    if (deletedImage) return `Usunąć obraz ${deletedImage[1]}?`;
    return text;
  }
  if (UI_STRINGS[text] !== undefined) return UI_STRINGS[text];
  for (const [plPrefix, enPrefix] of DYNAMIC_PREFIXES) {
    if (text.startsWith(plPrefix)) return `${enPrefix}${text.slice(plPrefix.length)}`;
  }
  const loadedCount = text.match(/^(\d+) wybranych(?: · limit osiągnięty)?$/);
  if (loadedCount) return `${loadedCount[1]} selected${text.endsWith("limit osiągnięty") ? " · limit reached" : ""}`;
  const modelCount = text.match(/^Dostępne modele: (\d+)$/);
  if (modelCount) return `Available models: ${modelCount[1]}`;
  const addedDocument = text.match(/^Dodano dokument „(.*)”\.$/);
  if (addedDocument) return `Added document “${addedDocument[1]}”.`;
  const selectedRag = text.match(/^Wybrano źródła RAG: (\d+)\.$/);
  if (selectedRag) return `Selected RAG sources: ${selectedRag[1]}.`;
  const deletedDocument = text.match(/^Usunąć „(.*)” z katalogu i kolekcji\?$/);
  if (deletedDocument) return `Delete “${deletedDocument[1]}” from the directory and collection?`;
  const deletedImage = text.match(/^Usunąć obraz (.*)\?$/);
  if (deletedImage) return `Delete image ${deletedImage[1]}?`;
  return text;
}

function translateAttribute(value, language) {
  return translateText(value, language);
}

const TRANSLATABLE_ATTRIBUTES = ["placeholder", "title", "aria-label", "aria-description", "alt"];
const SKIP_TEXT_SELECTOR = "pre, code, script, style, .thread-open, .model-pill";

function hasAncestor(element, predicate, root) {
  while (element && element !== root) {
    if (predicate(element)) return true;
    element = element.parentElement;
  }
  return false;
}

function isStaticOption(option) {
  if (!option?.matches?.("option")) return false;
  const label = option.textContent?.trim() || "";
  if (UI_STRINGS[label] === undefined && EN_TO_PL[label] === undefined) return false;
  const value = option.value ?? option.getAttribute?.("value") ?? "";
  if (value === "approve" || value === "reject") return true;
  if (value === "__new__") return true;
  if (value !== "") return false;
  const select = option.parentElement;
  return select?.id === "document-collection" || select?.id === "upload-collection" || select?.name === "model_name" ||
    Boolean(hasAncestor(select, (candidate) => candidate.matches?.(".review-controls"), null));
}

function isProtected(node, root, includeFormControls = false) {
  let element = node.nodeType === 1 ? node : node.parentElement;
  const inUiControl = hasAncestor(element, (candidate) => candidate.matches?.(".generated-image, .code-copy-btn"), root);
  const inStaticOption = hasAncestor(element, isStaticOption, root);
  const protectedText = (candidate) => candidate.matches?.(SKIP_TEXT_SELECTOR) ||
    candidate.matches?.(".message-body") && hasAncestor(candidate, (ancestor) => ancestor.matches?.(".message-user, .message-assistant"), root) && !inUiControl;
  if (hasAncestor(element, protectedText, root)) return true;
  if (!includeFormControls && !inStaticOption && hasAncestor(element, (candidate) => candidate.matches?.("input, textarea, select, option"), root)) return true;
  return false;
}

function translateNode(node, language, root) {
  if (node.nodeType === 3) {
    if (isProtected(node, root)) return;
    const translated = translateText(node.nodeValue, language);
    if (translated !== node.nodeValue) node.nodeValue = translated;
    return;
  }
  if (node.nodeType !== 1) return;
  const element = node;
  if (element.matches?.(SKIP_TEXT_SELECTOR)) return;
  if (!isProtected(element, root, true)) {
    for (const attribute of TRANSLATABLE_ATTRIBUTES) {
      if (!element.hasAttribute(attribute)) continue;
      const value = element.getAttribute(attribute);
      const translated = translateAttribute(value, language);
      if (translated !== value) element.setAttribute(attribute, translated);
    }
  }
  for (const child of element.childNodes) translateNode(child, language, root);
}

export function startI18n({ document = globalThis.document, storage = globalThis.localStorage, toggleSelector = "#language-toggle", preferenceApi = globalThis.window?.platonWindow } = {}) {
  if (!document?.documentElement || !document.body) return { language: "pl", setLanguage() {} };
  let language = "pl";
  try {
    language = storage?.getItem(STORAGE_KEY) === "en" ? "en" : "pl";
  } catch {}
  let observer;
  let applying = false;
  const apply = (nextLanguage, persist = true) => {
    language = nextLanguage === "en" ? "en" : "pl";
    document.documentElement.lang = language;
    try { storage?.setItem(STORAGE_KEY, language); } catch {}
    if (persist) {
      try { Promise.resolve(preferenceApi?.setPreference?.(STORAGE_KEY, language)).catch(() => {}); } catch {}
    }
    applying = true;
    translateNode(document.body, language, document.body);
    const toggle = document.querySelector(toggleSelector);
    if (toggle) {
      toggle.textContent = language === "pl" ? "EN" : "PL";
      toggle.setAttribute("aria-label", language === "pl" ? "Switch language to English" : "Zmień język na polski");
      toggle.setAttribute("title", language === "pl" ? "Switch language to English" : "Zmień język na polski");
    }
    applying = false;
  };
  apply(language, false);
  let languageChosen = false;
  try {
    Promise.resolve(preferenceApi?.getPreference?.(STORAGE_KEY)).then((saved) => {
      if (!languageChosen && (saved === "pl" || saved === "en")) apply(saved, false);
    }).catch(() => {});
  } catch {}
  if (typeof MutationObserver !== "undefined") {
    observer = new MutationObserver((records) => {
      if (applying) return;
      applying = true;
      for (const record of records) {
        if (record.type === "attributes") translateNode(record.target, language, document.body);
        else if (record.type === "characterData") translateNode(record.target, language, document.body);
        else for (const node of record.addedNodes) translateNode(node, language, document.body);
      }
      applying = false;
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: TRANSLATABLE_ATTRIBUTES });
  }
  document.addEventListener("click", (event) => {
    const toggle = event.target?.closest?.(toggleSelector);
    if (toggle) {
      languageChosen = true;
      apply(language === "pl" ? "en" : "pl");
    }
  });
  return { get language() { return language; }, setLanguage: apply, disconnect: () => observer?.disconnect() };
}

if (typeof window !== "undefined" && typeof document !== "undefined") startI18n();
