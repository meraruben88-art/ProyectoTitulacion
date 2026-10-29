# Imagen de SyllabusAI (API + interfaz). El modelo de lenguaje corre aparte (vLLM, ver compose).
#   docker build -f docker/Dockerfile -t syllabusai .
#   docker build -f docker/Dockerfile --build-arg EXTRAS=embeddings -t syllabusai:a100 .
FROM python:3.12-slim

ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# LibreOffice convierte DOCX a PDF con fidelidad (decisión D-7); sin él se usa el renderizador interno.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml requirements.lock README.md ./
COPY syllabusai ./syllabusai
RUN pip install -r requirements.lock && pip install ".${EXTRAS:+[$EXTRAS]}"

COPY config ./config
COPY ejemplos ./ejemplos
COPY eval ./eval
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Documentos institucionales del corpus de ejemplo (el manifiesto los busca en la raíz).
COPY ModeloEducativo.pdf Propuesta_nuevo_silabo_y_guia_UTI_2026.docx Guia_Construccion_PIS.docx ./

RUN chmod +x /usr/local/bin/entrypoint.sh && useradd --create-home syllabus \
    && mkdir -p /app/data && chown -R syllabus /app
USER syllabus

# data/ guarda la base relacional, Qdrant, el corpus, los puntos de control y los exportados.
VOLUME ["/app/data"]
EXPOSE 8080 8501
ENTRYPOINT ["entrypoint.sh"]
CMD ["api"]
