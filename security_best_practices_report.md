# Revisione di sicurezza — 17 ottobre 2026

La revisione mirata ha confermato un problema di disponibilità a severità **bassa** nel nuovo caricamento delle capacità dell'indice. È stato riprodotto su un database temporaneo e corretto. Non sono emersi altri problemi sfruttabili nei confini esaminati; questo esito non certifica l'assenza di vulnerabilità nell'intero prodotto.

## Perimetro e metodo

Tre revisioni indipendenti con GPT-6 Luna hanno esaminato il worker TypeScript, i metadati persistenti e la dashboard HTTP/frontend. L'agente principale ha verificato il risultato del caricamento JSON con un indice reale temporaneo e ha aggiunto regressioni automatiche. Le prove hanno usato esclusivamente dati sintetici locali.

La revisione riguarda Python standard library, Node/TypeScript e JavaScript del browser. È stata applicata la skill `security-best-practices`, con la guida per frontend JavaScript generico. La skill non contiene una guida specifica per il backend HTTP custom in uso: quel confine è stato verificato sul codice e sul modello di minaccia documentato in `docs/security.md`.

Sono esclusi root, processi ostili con lo stesso UID e accesso già disponibile a terminale, memoria o storage del browser dell'utente. Non è stato eseguito un controllo completo degli advisory delle dipendenze o un penetration test esterno.

## SEC-001 — Bassa — JSON di forma errata interrompeva refresh (corretto)

**Posizione:** `init_agent/analysis_capabilities.py:104`, richiamato da `init_agent/refresh.py:37`.

Prima della correzione, `load_capabilities` chiamava `json.loads` e poi `value.setdefault` senza verificare che il valore fosse un oggetto. Un record con `metadata_json='[]'` provocava:

```text
AttributeError: 'list' object has no attribute 'setdefault'
```

**Riproduzione:** creare un indice temporaneo con un file Python, sostituire il campo `file_analysis.metadata_json` con `[]`, chiamare `refresh_index`. L'eccezione usciva dalla funzione perché il caricamento precede il blocco di gestione degli errori.

**Impatto e prerequisiti:** interruzione locale dell'aggiornamento in presenza di metadati corrotti o manipolati. Non sono stati dimostrati lettura esterna alla repository, esecuzione di codice o accesso non autenticato. Il database è protetto dal confine owner-only già presente, che riduce l'esposizione.

**Correzione:** riuso di `decode_persisted_object`, con verifica del tipo oggetto e limiti di byte, profondità e struttura; fingerprint non valido trattato come analisi da ricostruire. Il caricamento ora scorre le righe senza materializzare preventivamente tutta la query. I test coprono array, null, booleani, numeri, stringhe, fingerprint di tipo errato e JSON profondamente annidato.

**Regressione:** `tests/test_analysis_capabilities.py`, test `test_corrupt_capability_roots_are_reindexed_without_crashing`. L'aggiornamento termina con stato `OK` e ricostruisce il file interessato.

## Confini verificati senza vulnerabilità confermate

- **Worker TypeScript:** percorso relativo e controlli su symlink, ambiente Node ridotto, compilatore locale bloccato, nessun caricamento di script/plugin del progetto; limiti di tempo/output, heap V8, file e byte letti. Riferimenti di progetto non supportati e sorgenti malformate falliscono senza produrre collegamenti strutturali.
- **Letture dei percorsi:** `evidence_trace` usa aperture descriptor-relative `O_NOFOLLOW`, verifica hash e limiti di lettura. Non è stata trovata una lettura fuori dalla radice.
- **Dashboard:** loopback, Host/Origin e bearer prima dell'accesso ai dati; escaping di contenuti derivati dalla repository. La prova con stringhe contenenti script e attributi HTML non ha prodotto markup eseguibile. La presenza di `document.write` nel bootstrap, da sola, non costituisce una vulnerabilità: il contenuto proviene dalla risposta autenticata e renderizzata dal server.

L'assenza di una CSP visibile è una possibile misura aggiuntiva di hardening, non un exploit confermato. Nessuna modifica alla dashboard è stata effettuata.

## Collegamento con la verifica di utilità

Questa attività fornisce un caso reale di revisione e una regressione riproducibile. Non dispone però di sessioni abbinate con/senza init-agent, controllo delle letture o misure comparabili di tempo e contesto. La soglia del 20% rimane **non valutata**; il recupero delle prove resta facoltativo.

## Verifiche finali

- Suite completa: 485 test, esito positivo, 4 saltati per disponibilità di parser/piattaforma.
- Ambiente temporaneo con PHP reale: 22 test di capacità, percorsi e parser, tutti superati.
- I test della suite che aprono un socket Unix temporaneo sono stati eseguiti fuori dal sandbox del terminale dopo aver verificato il motivo del blocco.

È stata inoltre corretta una regressione di stato del parser: un file privo di
contenuto testuale non eredita più l'analizzatore del file precedente e non viene
segnalato come ricercabile testualmente.
