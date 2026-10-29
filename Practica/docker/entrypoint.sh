#!/bin/sh
# Prepara el corpus de ejemplo la primera vez y arranca el servicio pedido.
set -e
if [ ! -f /app/data/syllabusai.db ] && [ "${SYLLABUSAI_PREPARAR_EJEMPLO:-1}" = "1" ]; then
    syllabusai ejemplo
fi
case "$1" in
    api) exec syllabusai api --host 0.0.0.0 --port 8080 ;;
    ui) exec syllabusai ui --host 0.0.0.0 --port 8501 ;;
    *) exec syllabusai "$@" ;;
esac
