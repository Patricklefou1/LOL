#!/usr/bin/env bash
#
# Recap quotidien du releve des cotations, envoye par mail.
#
# Contenu : les evenements de la veille (lancements et premiers perps, avec la
# liste de ceux qui touchent une bourse de rang 1), puis les moyennes sur 15
# jours. Le sujet porte [ALERTE] si une source a echoue sur les dernieres 24 h :
# un trou de releve date les cotations en retard, il faut le savoir avant de
# lire un chiffre.
#
# Envoi par msmtp, sans fichier de configuration : tout vient de ../.env.
#   MAIL_TO        destinataire
#   SMTP_HOST      par defaut smtp.gmail.com
#   SMTP_PORT      par defaut 587
#   SMTP_USER      compte expediteur
#   SMTP_PASSWORD  pour Gmail, un mot de passe d'application, jamais le vrai
#
# LECTURE SEULE sur les tables. Aucun secret n'est affiche ni journalise.

set -euo pipefail

CAPTURE_DIR=${CAPTURE_DIR:-/opt/pumpfun/LOL/capture}
ENV_FILE=$CAPTURE_DIR/.env

journal() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
echec()   { journal "ECHEC: $*"; exit 1; }

[ -r "$ENV_FILE" ] || echec "$ENV_FILE illisible (lancer sous l'utilisateur pumpfun)"
lire_env() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; }

MAIL_TO=$(lire_env MAIL_TO)
SMTP_HOST=$(lire_env SMTP_HOST); SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}
SMTP_PORT=$(lire_env SMTP_PORT); SMTP_PORT=${SMTP_PORT:-587}
SMTP_USER=$(lire_env SMTP_USER)
SMTP_PASSWORD=$(lire_env SMTP_PASSWORD)
for v in MAIL_TO SMTP_USER SMTP_PASSWORD; do
  [ -n "${!v}" ] || echec "$v absent de $ENV_FILE"
done
command -v msmtp >/dev/null || echec "msmtp absent : sudo apt install msmtp"

cd "$CAPTURE_DIR"
VEILLE=$(node dist/listings.js --rapport 1 2>&1) || echec "rapport de la veille : $VEILLE"
QUINZE=$(node dist/listings.js --rapport 15 --sans-detail 2>&1) || echec "rapport 15 jours : $QUINZE"

JOUR=$(date -u -d yesterday +%d/%m/%Y)
SUJET="Listings du $JOUR"
if grep -qE ' [1-9][0-9]* échecs|jamais relevée' <<<"$VEILLE"; then
  SUJET="[ALERTE] $SUJET : relevé incomplet"
fi

# Le corps est en texte brut a chasse fixe : les tableaux restent alignes dans
# un client qui affiche le texte brut, Gmail compris si on ouvre le message
# d'origine.
{
  printf 'To: %s\n' "$MAIL_TO"
  printf 'From: Releve listings <%s>\n' "$SMTP_USER"
  printf 'Subject: =?UTF-8?B?%s?=\n' "$(printf '%s' "$SUJET" | base64 -w0)"
  printf 'MIME-Version: 1.0\n'
  printf 'Content-Type: text/plain; charset=UTF-8\n'
  printf 'Content-Transfer-Encoding: 8bit\n\n'
  printf '=== Veille ===\n\n%s\n\n' "$VEILLE"
  printf '=== 15 derniers jours ===\n\n%s\n' "$QUINZE"
} | SMTP_PASSWORD="$SMTP_PASSWORD" msmtp \
      --host="$SMTP_HOST" --port="$SMTP_PORT" --tls=on --auth=on \
      --user="$SMTP_USER" --from="$SMTP_USER" \
      --passwordeval='printf %s "$SMTP_PASSWORD"' \
      "$MAIL_TO" || echec "envoi msmtp"

journal "recap envoye : $SUJET"
