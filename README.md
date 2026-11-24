# Analisi dei pericoli

Portale Django e PostgreSQL per compilare, pubblicare e consultare le valutazioni dei rischi aziendali.

## Avvio con i container

Servono Podman con un provider Compose oppure Docker con il plugin Compose. I comandi seguenti usano `podman compose`. Con Docker usa `docker compose`. Se manca il provider per Podman, puoi installarlo in un ambiente virtuale attivo con `python -m pip install podman-compose`.

Copia la configurazione di esempio e imposta in `.env` una password locale per `PORTALE_DB_PASSWORD`. Poi costruisci l'immagine e applica le migrazioni.

```sh
cp -n .env.example .env
# Imposta PORTALE_DB_PASSWORD in .env prima di proseguire.
podman compose build web
podman compose up -d --wait db
podman compose run --rm web python manage.py migrate --noinput
```

Su un database nuovo puoi importare il catalogo in un secondo momento. Usa un file Excel esterno nel formato previsto dal comando `importa_catalogo` e montalo in sola lettura. Il comando pubblica la prima versione e rifiuta di sovrascrivere un catalogo esistente.

```sh
podman compose run --rm \
  -v "/percorso/catalogo.xlsx:/import/catalogo.xlsx:ro" \
  web python manage.py importa_catalogo /import/catalogo.xlsx
podman compose run --rm web python manage.py createsuperuser
```

Avvia il portale con `podman compose up -d web` e apri [il portale in container](http://127.0.0.1:8080/). Per scegliere un'altra porta imposta `PORTALE_WEB_PORT` in `.env`. PostgreSQL è raggiungibile sulla rete Compose come `db:5432`. Il catalogo, gli utenti e le valutazioni risiedono nel volume `postgres-data` del progetto. `podman compose down` arresta lo stack e conserva il volume. Per eseguire i test con la configurazione locale usa `podman compose run --rm web python manage.py test --noinput`.

### Rilascio sulla VM

1. Assegna all'immagine verificata un tag di release. Trasferiscila con `podman save` e `podman load` oppure tramite un registro privato. Copia `compose.yaml` sulla VM e imposta `PORTALE_IMAGE` al riferimento esatto dell'immagine caricata.
2. Prepara sulla VM un file `.env` con permessi di lettura limitati. Imposta `PORTALE_DEBUG=0`, una `PORTALE_SECRET_KEY` casuale e stabile, `PORTALE_ALLOWED_HOSTS` con il nome DNS e `PORTALE_DB_NAME`, `PORTALE_DB_USER`, `PORTALE_DB_PASSWORD` con i parametri del database dedicato.
3. Configura il proxy HTTPS della VM verso `127.0.0.1:8080` preservando l'header `Host`. Se il proxy sostituisce ogni `X-Forwarded-Proto` ricevuto dal client con lo schema della connessione e controlli tutti gli accessi al backend, imposta `PORTALE_TRUST_PROXY_HTTPS=1`. Questo permette a Django di riconoscere le richieste HTTPS.
4. Avvia `db` con `podman compose up -d --wait db`. Per trasferire dati esistenti, ripristina il backup PostgreSQL nel database vuoto. Per ogni rilascio esegui `podman compose run --rm web python manage.py check --deploy` e `podman compose run --rm web python manage.py migrate --noinput`. Su un database nuovo completa l'importazione e la creazione dell'amministratore descritte sopra.
5. Avvia la release con `podman compose up -d --no-build web`. Verifica l'accesso via HTTPS, i fogli di stile del portale e dell'amministrazione e l'apertura di una valutazione. I file statici sono già inclusi nell'immagine.

## Avvio locale

Servono Python 3.10 o successivo e PostgreSQL 14 o successivo. Imposta le variabili `PORTALE_DB_*` in `.env` con i parametri del tuo database.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
# Imposta i parametri di connessione in .env prima di proseguire.
set -a
. ./.env
set +a
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Per importare il catalogo in un database nuovo esegui `python manage.py importa_catalogo /percorso/catalogo.xlsx`.

Apri [il portale locale](http://127.0.0.1:8000/). L’operatore crea le aziende dal portale. L’amministratore crea gli utenti in `/amministrazione/` e assegna il gruppo **Operatore** oppure **Cliente**. Per il cliente seleziona anche l’azienda. Le password si impostano e si reimpostano dal pannello. Gli utenti con accesso possono cambiare la propria password dal menu utente.

La probabilità accetta la virgola o il punto come separatore decimale e conserva fino a 12 cifre decimali. La matrice mostra il risultato esatto e assegna la fascia al valore calcolato.

## Verifiche

Con l’ambiente già attivato, esegui `python manage.py test --noinput`. Django crea e rimuove un database di test separato. Il ruolo PostgreSQL di sviluppo deve quindi poter creare database.

Per un avvio su un’altra macchina configura una chiave segreta distinta con `PORTALE_SECRET_KEY`, gli host con `PORTALE_ALLOWED_HOSTS` e il database con `PORTALE_DB_*`. Usa HTTPS con `PORTALE_DEBUG` disattivato e raccogli i file statici con `python manage.py collectstatic`.
