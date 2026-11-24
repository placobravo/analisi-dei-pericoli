# Analisi dei pericoli

Portale Django e PostgreSQL per compilare, pubblicare e consultare le valutazioni dei rischi aziendali.

## Avvio con Podman Kube

Il manifest `podman-kube.yml` avvia Django e PostgreSQL nello stesso pod con Podman rootless. Il portale ascolta su [127.0.0.1:8080](http://127.0.0.1:8080/) e usa il volume dedicato `analisi-pericoli-kube-data`.

Al primo avvio crea il Secret nel deposito locale di Podman. Conserva queste credenziali per i successivi avvii con lo stesso volume.

```sh
python3 - <<'PY' | podman kube play -
import json
import secrets
print(json.dumps({
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": "analisi-pericoli-kube-secrets"},
    "stringData": {"db-password": secrets.token_hex(32), "django-key": secrets.token_hex(48)},
}))
PY
```

Costruisci l'immagine, avvia il pod e applica le migrazioni appena PostgreSQL è pronto. Su un nuovo database crea anche il primo amministratore.

```sh
podman build -t localhost/analisi-dei-pericoli:kube .
podman kube play podman-kube.yml
podman wait --condition=healthy analisi-pericoli-kube-db
podman exec analisi-pericoli-kube-web python manage.py migrate --noinput
podman exec -it analisi-pericoli-kube-web python manage.py createsuperuser
```

Per importare il catalogo in un database nuovo, passa il foglio esterno al comando tramite lo standard input. Il file temporaneo viene rimosso al termine.

```sh
podman exec -i analisi-pericoli-kube-web sh -ec '
  file=$(mktemp --suffix=.xlsx)
  trap "rm -f -- $file" EXIT
  cat > "$file"
  python manage.py importa_catalogo "$file"
' < /percorso/catalogo.xlsx
```

Per arrestare il pod e conservare il database usa `podman kube down podman-kube.yml`. Dopo un aggiornamento ricostruisci l'immagine, esegui `podman kube play --replace podman-kube.yml`, attendi PostgreSQL e ripeti le migrazioni.

## Utilizzo

L’operatore crea le aziende dal portale. L’amministratore crea gli utenti in `/amministrazione/` e assegna il gruppo **Operatore** oppure **Cliente**. Per il cliente seleziona anche l’azienda. Le password si impostano e si reimpostano dal pannello. Gli utenti con accesso possono cambiare la propria password dal menu utente.

La probabilità accetta la virgola o il punto come separatore decimale e conserva fino a 12 cifre decimali. La matrice mostra il risultato esatto e assegna la fascia al valore calcolato.

## Verifiche

Sul pod locale esegui la suite Django. Il comando crea e rimuove un database di test separato.

```sh
podman exec analisi-pericoli-kube-web python manage.py test --noinput
```

## Rilascio sulla VM

1. Trasferisci l’immagine verificata con `podman save` e `podman load` oppure prelevala dal registro con `podman pull`. Nella copia di `podman-kube.yml` destinata alla VM indica il tag di release nel campo `image` del container `web`.
2. Alla prima installazione crea il Secret sulla VM. Nelle variabili del container `web` imposta `PORTALE_DEBUG` a `"0"` e `PORTALE_ALLOWED_HOSTS` al nome DNS del portale.
3. Configura il proxy HTTPS verso la porta loopback del pod, preservando l’header `Host`. Imposta `PORTALE_TRUST_PROXY_HTTPS=1` se controlli gli accessi al backend e il proxy sovrascrive `X-Forwarded-Proto` con lo schema della connessione originale.
4. Avvia il pod, attendi PostgreSQL e applica le migrazioni come descritto sopra. Per trasferire dati esistenti, ripristina il backup nel database vuoto prima delle migrazioni. Esegui `podman exec analisi-pericoli-kube-web python manage.py check --deploy` e verifica l’accesso via HTTPS.
