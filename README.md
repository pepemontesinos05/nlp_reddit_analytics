# Análisis de contenido de Reddit con PLN

**Autores:** Jose Montesinos Pineda y Enrique Vicente Pujante

Proyecto de Procesamiento del Lenguaje Natural (PLN) sobre contenido de
Reddit. A partir de un corpus propio de hilos y comentarios de varios
subreddits, el proyecto aborda seis tareas típicas de PLN de principio a
fin: construcción y análisis del corpus, clasificación de texto, similitud
semántica de documentos, análisis de sentimiento, resumen automático y
detección de contenido inapropiado con modelos de lenguaje.

## Propósito

Reddit está organizada en *subreddits* temáticos donde los usuarios publican
hilos (*submissions*) y comentan sobre ellos. Este proyecto parte de un
volcado de datos de Reddit de 2025 y construye, para 6 subreddits elegidos
(Python, Chemistry, Investing, Soccer, Cooking y Autism), un corpus propio
con el que se exploran las siguientes tareas:

1. **Compilación y análisis del corpus**: extracción, filtrado y estadísticas
   descriptivas del texto recopilado (longitud de comentarios, vocabulario
   más frecuente por subreddit, distribución temporal, etc.).
2. **Clasificación de comentarios por subreddit**: dado el texto de un
   comentario, predecir a qué subreddit pertenece, comparando
   representaciones clásicas (BoW, TF-IDF), *word embeddings* (FastText) y
   modelos Transformer *fine-tuneados* (mBERT).
3. **Búsqueda de hilos similares**: *sentence embeddings* (FastText y
   *sentence-transformers*) para encontrar qué hilos son más parecidos entre
   sí dentro de un mismo subreddit, con visualización 2D y mapas de calor de
   similitud.
4. **Análisis de subjetividad**: extracción de la polaridad (positivo/
   neutro/negativo) de los comentarios.
5. **Resumen automático abstractivo**: generación de resúmenes de cada hilo
   con un modelo *seq2seq* ya entrenado (mT5) y con *small language models*
   (SLMs) en modo *zero-shot*.

## Estructura del proyecto

```
.
├── README.md
├── requirements.txt
├── .gitignore
├── data/                              # Corpus y resultados generados
│   ├── <Subreddit>_filtrado.json              # Corpus por subreddit (x6)
│   ├── <Subreddit>_filtrado_con_sentimiento.json  # + sentimiento por comentario (x6)
│   ├── <Subreddit>_resumido_FINAL.json         # + resúmenes por hilo (x6)
│   ├── OpinionesPolemicas_filtrado.json
│   ├── OpinionesPolemicas_resultados_inapropiado.json
│   ├── train.json                     # Split de entrenamiento del clasificador
│   ├── test.json                      # Split de validación del clasificador
│   └── split_summary.txt
├── scripts/
│   └── 00_descarga_datos.py           # Descarga y filtrado del corpus desde Reddit
└── notebooks/
    ├── 01_eda.ipynb                   # Corpus y análisis exploratorio (EDA)
    ├── 02_clasificador.ipynb          # Clasificador de comentarios por subreddit
    ├── 03_similitud_hilos.ipynb       # Búsqueda de hilos similares
    ├── 04_subjetividad.ipynb          # Análisis de subjetividad
    └── 05_resumen.ipynb               # Resumen automático abstractivo

```

Cada notebook es independiente y autoexplicativo (incluye el razonamiento,
el código y los resultados ya ejecutados), y carga los datos desde `data/`
con una ruta relativa (`DATA_DIR = Path('../data')`), por lo que se ejecutan
desde dentro de la carpeta `notebooks/`.

## Cómo inicializar el proyecto

### Requisitos

- Python 3.10+
- (Opcional, recomendado para los notebooks 2, 3, 5 y 6) una GPU y acceso a
  internet para descargar modelos de Hugging Face (BERT, FastText,
  *sentence-transformers*, SLMs tipo Gemma/Llama). Un entorno como Google
  Colab funciona bien para esto.

### Instalación

```bash
# Crear y activar un entorno virtual
python3 -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

### Ejecutar los notebooks

El corpus ya viene generado dentro de `data/`, así que los notebooks se
pueden abrir y ejecutar directamente sin pasos previos:

```bash
jupyter notebook notebooks/
```

### (Opcional) Regenerar el corpus desde cero

El script `scripts/00_descarga_datos.py` descarga los volcados de Reddit,
los filtra a los subreddits elegidos y construye los ficheros JSON del
corpus:

```bash
# Ver todas las opciones
python scripts/00_descarga_datos.py --help

# Ejecutar el proceso completo (descarga + filtrado + extracción)
python scripts/00_descarga_datos.py --all
```
