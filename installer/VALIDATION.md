# Walidacja 2026-11-14

Przegląd workflowów po rozdzieleniu Linux/macOS: `actionlint` 1.7.12 nie zgłosił błędów dla czterech plików (Windows, Linux, macOS i wspólny release). Sprawdzono ręczne wyzwalacze, zgodność nazw artefaktów, zależności wspólnego wydania oraz obecność testów we wszystkich buildach. Lokalnie przeszło 18 testów konfiguracji desktopowej, środowiska wykonawczego i pobierania generatora obrazów. Dwa testy normalizują ścieżki tymczasowe przez `resolve()`, aby uwzględnić dowiązania katalogów na macOS. Nie uruchamiano GitHub Actions ani natywnych buildów macOS/Linux w ramach tego przeglądu.

Potwierdzone lokalnie na Windows x64:

- 62 testy frontendu przeszły (`npm test` w `platon_frontend`).
- Testy konfiguracji desktopowej, pomijania/pobierania modeli, instalacji komponentów obrazowych na Windows, błędów pobierania i autoryzacji konfiguracji przeszły.
- Testy tworzenia środowiska agenta i wykonywania kodu oraz dotychczasowe testy API i obrazów przeszły.
- PyInstaller utworzył `installer/staging/backend/platon-backend.exe`.
- Gotowy backend przeszedł `--self-test`: zasoby promptów, endpoint health, utworzenie venv i wykonanie kodu dołączonym Pythonem.
- Rzeczywiście uruchomiony backend onefile odpowiedział HTTP 200 na `/health`.
- W paczce Electron sprawdzono obecność backendu, interpretera, ekranu konfiguracji i pliku kanału aktualizacji.
- Oba workflow GitHub Actions mają ręczny wyzwalacz; sprawdzono YAML. Nie uruchamiano ich ani nie publikowano wydania.

Nie wykonano natywnych buildów/testów macOS i Linux, instalacji na czystym komputerze, pobrania wielogigabajtowych modeli podczas testu ani aktualizacji pomiędzy opublikowanymi wydaniami. Pobieranie modeli sprawdzono testami z zastąpionymi odpowiedziami sieciowymi; testy backendu onefile nie uruchamiają konfiguracji modeli. Certyfikaty dystrybucyjne nie zostały skonfigurowane.

Instalator NSIS: `installer/dist/Platon.ai Setup 0.1.0.exe`, 512374073 bajty. Build electron-builder zakończył się kodem 0. Manifest `latest.yml` ma zgodną sumę SHA-512 i rozmiar; powstał plik blockmap. Podpis Authenticode: `NotSigned`. Nie uruchamiano instalatora.

SHA-256: `b4fddd3a51becb407df51a07ce9b5565a5a11499e5afc77d14d92171e2edd366`.
