# Instalacja Ollamy i modeli

Ten dokument opisuje przygotowanie Ollamy dla projektu Platon. Ollama jest
lokalnym serwerem modeli językowych, z którym aplikacja komunikuje się przez
HTTP na porcie `11434`.

## Wymagania sprzętowe

Model `ornith-1.5:35b` jest domyślnym modelem projektu i wymaga dużo pamięci.
Przed pobraniem sprawdź wolne miejsce na dysku oraz pamięć RAM/VRAM. Jeżeli
komputer lub serwer jest słabszy, można ustawić mniejszy model przez
`OLLAMA_MODEL` (przykład znajduje się niżej).

## Instalacja na Windows

1. Pobierz i zainstaluj Ollamę z [ollama.com/download](https://ollama.com/download).
2. Uruchom Ollamę. Powinna działać jako proces w tle.
3. W PowerShellu sprawdź instalację:

   ```powershell
   ollama --version
   Invoke-RestMethod http://localhost:11434/api/version
   ```

4. Pobierz model używany domyślnie przez projekt:

   ```powershell
   ollama pull ornith-1.5:35b
   ```

5. Sprawdź, czy model jest dostępny:

   ```powershell
   ollama list
   ollama run ornith-1.5:35b
   ```

   W interaktywnym trybie wpisz krótkie pytanie, a następnie zakończ program
   skrótem `Ctrl+C`.

Jeżeli `ollama` nie jest widoczna w PowerShellu, zamknij i otwórz terminal
ponownie. Gdy problem nadal występuje, uruchom aplikację Ollamy z menu Start
i sprawdź, czy katalog instalacyjny Ollamy znajduje się w `PATH`.

## Instalacja na Linuxie

Poniższe polecenia są przeznaczone dla Ubuntu/Debian i wymagają konta z
uprawnieniami `sudo`.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

Po instalacji włącz usługę i sprawdź jej status:

```bash
sudo systemctl enable --now ollama
systemctl status ollama --no-pager
curl http://127.0.0.1:11434/api/version
```

Pobierz model projektu:

```bash
ollama pull ornith-1.5:35b
ollama list
```

Test ręczny:

```bash
ollama run ornith-1.5:35b
```

Na serwerze z kartą NVIDIA upewnij się dodatkowo, że sterownik NVIDIA jest
zainstalowany i widoczny dla systemu (`nvidia-smi`). Ollama sama wykorzysta
GPU, jeśli środowisko jest poprawnie skonfigurowane. Bez GPU model będzie
działał na CPU, ale odpowiedzi mogą być znacznie wolniejsze.

## Modele używane przez projekt

### Model wymagany

```bash
ollama pull ornith-1.5:35b
```

To model ustawiony domyślnie w konfiguracji Platon (`AgentConfig.model_name`).
Nazwa w komendzie musi dokładnie odpowiadać wartości ustawionej w
`OLLAMA_MODEL`.

### Mniejszy model na słabszy komputer lub serwer

Jeżeli `ornith-1.5:35b` jest zbyt duży, wybierz model dostępny w bibliotece
Ollamy, który obsługuje rozmowę i wywoływanie narzędzi, na przykład:

```bash
ollama pull qwen3:8b
ollama list
```

Następnie ustaw:

```dotenv
OLLAMA_MODEL=qwen3:8b
```

Dobór modelu wpływa na jakość planowania i wywoływania narzędzi. Po zmianie
modelu wykonaj test opisany w sekcji [Weryfikacja](#weryfikacja).

### Embeddingi

Projekt nie pobiera embeddingów przez Ollamę. Domyślny model embeddingów
`Qwen/Qwen3-Embedding-0.6B` jest pobierany przez `sentence-transformers`
z Hugging Face przy pierwszym użyciu i zapisywany w lokalnym cache. Na serwerze
trzeba więc zapewnić również dostęp do Internetu podczas pierwszego uruchomienia
modułu wektorowego albo wcześniej przygotować cache modelu.

## Konfiguracja projektu

W pliku `.env` ustaw adres Ollamy i model. Dla Ollamy działającej na tym samym
komputerze:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=ornith-1.5:35b
OLLAMA_NUM_CTX=16384
```

Po zmianie `.env` uruchom aplikację z katalogu głównego projektu:

```powershell
uv run python run_agent_chat_ui.py
```

albo na Linuxie:

```bash
uv run python run_agent_chat_ui.py
```

`OLLAMA_NUM_CTX` określa rozmiar kontekstu. Większa wartość może poprawić pracę
z długimi dokumentami, ale zwiększa zużycie pamięci.

## Ollama na osobnym serwerze Linuxowym

Najbezpieczniejszym rozwiązaniem jest pozostawienie Ollamy dostępnej tylko na
`127.0.0.1` i połączenie przez tunel SSH.

Na komputerze, na którym działa Platon:

```bash
ssh -N -L 11434:127.0.0.1:11434 user@adres-serwera
```

W drugim terminalu ustaw:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=ornith-1.5:35b
```

Tunel pozostaw uruchomiony podczas korzystania z aplikacji. W ten sposób nie
trzeba otwierać portu Ollamy w Internecie.

### Bezpośredni dostęp w sieci prywatnej

Jeżeli tunel SSH nie jest możliwy, Ollama może nasłuchiwać na interfejsie
serwera. Edytuj usługę:

```bash
sudo systemctl edit ollama
```

Dodaj:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Zastosuj zmianę:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Ogranicz port firewallem wyłącznie do adresów zaufanej sieci. Przykład dla
UFW, gdzie `192.168.1.0/24` jest siecią klienta:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 11434 proto tcp
sudo ufw status
```

Na komputerze z Platonem ustaw adres serwera:

```dotenv
OLLAMA_BASE_URL=http://192.168.1.10:11434
OLLAMA_MODEL=ornith-1.5:35b
```

Nie wystawiaj portu `11434` publicznie bez dodatkowej warstwy ochrony, takiej
jak VPN albo reverse proxy z uwierzytelnianiem. Ollama nie powinna być
traktowana jako publiczny, anonimowy endpoint.

## Weryfikacja

Najpierw sprawdź sam serwer:

```bash
curl http://localhost:11434/api/version
ollama list
```

Następnie sprawdź generowanie odpowiedzi bez uruchamiania całej aplikacji:

```bash
ollama run ornith-1.5:35b "Odpowiedz jednym zdaniem: czy Ollama działa?"
```

Na końcu uruchom test aplikacji:

```bash
uv run python run_agent_chat_ui.py
```

Jeżeli aplikacja zgłasza `connection refused`, sprawdź kolejno:

1. czy działa `systemctl status ollama` (Linux) albo aplikacja Ollama
   (Windows);
2. czy `OLLAMA_BASE_URL` wskazuje właściwy host i port;
3. czy `ollama list` zawiera model ustawiony w `OLLAMA_MODEL`;
4. czy firewall serwera pozwala na połączenie;
5. czy tunel SSH nadal działa, jeśli używana jest konfiguracja tunelowana.

## Aktualizacja i miejsce na dysku

Modele zajmują dużo miejsca. Listę pobranych modeli i ich rozmiary sprawdzisz:

```bash
ollama list
```

Niepotrzebny model usuń jawnie:

```bash
ollama rm nazwa-modelu
```

Przed aktualizacją modelu zapisz nazwę aktualnie używaną przez środowisko
produkcyjne. Zmiana modelu może zmienić jakość odpowiedzi, obsługę narzędzi
oraz wymagania pamięciowe.
