# CodeLens AI

> **An AI-Powered Multi-Agent System for Open Source Project Analysis and Software Comprehension**

CodeLens AI is an academic engineering project designed to help software engineers, students, and researchers comprehend unfamiliar open-source software repositories. By combining automated AST parsing, dependency extraction, architectural graph modeling, and multi-agent intelligence, CodeLens AI reduces the steep cognitive barrier required to understand complex codebases.

---

## Current Status: Phase 8 (Whole Repository Architecture Explorer)

This repository currently reflects **Phase 8** of the project lifecycle.

- **Objective**: Transform the Semantic Code Graph into an interactive, multi-level **Whole Repository Architecture Explorer** that enables a developer or evaluator to comprehend overall repository architecture across 4 hierarchical tiers, detect dependency cycles, identify highly connected architectural hubs with centrality metrics, search and filter across components, and view a deterministic architecture dossier.
- **Implemented in Phase 8**:
  - **Whole Repository Architecture Service (`services/architecture_service.py`)**:
    - **4-Level Hierarchical Navigation**:
      - **Level 1 (Repository Overview)**: Root repository node, major directory subsystem clusters, and top-level entry files.
      - **Level 2 (Directory / Subsystem Organization)**: Package directories mapped to their contained files with symbol tallies.
      - **Level 3 (File / Module Structural Scope)**: Focused files containing their declared classes, functions, methods, and imported modules.
      - **Level 4 (Entity / Symbol Relationships)**: Granular symbol graph with typed relationships (`inherits`, `calls`, `defines`, `imports`).
    - **Dependency Analysis & Cycle Detection**:
      - Separates internal module dependencies (`file -> file`) from external packages and standard library imports.
      - Implements directed cycle detection using NetworkX `nx.is_directed_acyclic_graph` and `nx.simple_cycles` to find circular import loops or mathematically prove a clean Directed Acyclic Graph (DAG).
    - **Architectural Hubs & Centrality Analysis**:
      - Computes in-degree, out-degree, total connections, and normalized degree centrality.
      - Generates explainable, factual role tags (`Architectural Backbone / Core Hub`, `Coordinator / High Orchestrator`, `Shared Dependency / Utility Hub`).
    - **Execution Entry Points**:
      - Detects application bootstrap points (`__main__` block, `public static void main`, top-level launcher routines).
    - **Deterministic Architecture Dossier**:
      - Synthesizes verified summary bullets based purely on real AST and graph statistics (zero hallucination).
    - **Persistent Architecture Storage**:
      - Cached to repository-isolated JSON files in `data/architecture/{owner}_{name}_architecture.json`.
  - **Whole Repository Architecture Explorer UI (`templates/architecture.html` & `static/js/main.js`)**:
    - **Breadcrumbs & Level Navigation Bar**: Real-time breadcrumbs and level switcher pills (`L1: Overview`, `L2: Directory`, `L3: File`, `L4: Entity`).
    - **Target Repository Header Card**: Name, GitHub link, primary language badge, cache status, and circular dependency status.
    - **8 Architecture Statistics Cards**: Source Files, Directories, Classes, Functions, Methods, Dependencies, Entry Points, Cycles Detected.
    - **Real-Time Architecture Search & Dropdown**: Autocomplete across all entities with direct level switching and component focusing.
    - **Interactive HTML5 Architecture Canvas**: High-DPI Retina display support, pan, scroll zoom, directed arrows, hover highlighting, and double-click to drill down into deeper levels.
    - **Selected Component Inspector**: Component details, contained symbols, centrality score, incoming inputs, outgoing outputs, and drill-down action buttons.
    - **Structural Insights Grid**: Dependency Cycle Analysis card (clean DAG checkmark vs circular loops) + Highly Connected Hubs card (centrality percentages and explainable tags).
    - **Execution Entry Points Section**: Shows detected bootstrap files, reasons, and execution commands.
    - **Deterministic Architecture Dossier**: Factual summary bullets of codebase scale, language distribution, dependency breakdown, and cycle status.
  - **REST API Endpoints**:
    - `POST /api/repositories/architecture`: Generates or retrieves the complete multi-level architecture model.
    - `GET /api/repositories/architecture/<owner>/<name>`: Retrieves stored architecture JSON.
    - `GET /api/repositories/architecture/<owner>/<name>/cycles`: Retrieves cycle detection results specifically.
    - `GET /architecture`: Renders the Architecture Explorer UI.
  - **71 Automated Tests**: 100% test pass rate across all 8 phases.
- **Reference**: See [`PROJECT_PHASES_SUMMARY.md`](PROJECT_PHASES_SUMMARY.md) for the complete phase-by-phase academic guide.

---

## Technology Stack

- **Backend**: Python 3.11+, Flask 3.x
- **Graph Modeling & Network Algorithms**: NetworkX 3.x (`nx.DiGraph`, cycle detection, centrality)
- **AST & Code Parsing**: Standard Library `ast`, `javalang 0.13.0`
- **Repository Acquisition**: GitPython 3.1+, Git CLI
- **Network / API**: Python Standard Library `urllib.request` / `urllib.parse` / `urllib.error`
- **Configuration**: python-dotenv
- **Frontend**: HTML5 Canvas, CSS3 (Modern Dark Dashboard theme), JavaScript (ES6+), Jinja2
- **Testing**: Python standard `unittest` framework (71 automated unit and integration tests)

---

## Project Structure

```text
CodeLens-AI/
│
├── app.py                     # Flask application factory registering blueprints
├── requirements.txt           # Project dependencies (Flask, NetworkX, GitPython, javalang)
├── .env.example               # Example environment variable template
├── .gitignore                 # Git ignore rules for Python, virtualenv, and caches
├── README.md                  # Comprehensive academic documentation
├── PROJECT_PHASES_SUMMARY.md  # Detailed phase-by-phase academic guide & Viva prep
│
├── config/
│   ├── __init__.py            # Config module exports
│   └── config.py              # Environment configuration classes (Dev, Prod, Test)
│
├── routes/
│   ├── __init__.py            # Blueprint exports
│   ├── main_routes.py         # Primary landing page, /analysis, /architecture, and /health check
│   └── repository_routes.py   # API endpoints for validation, search, ranking, clone, AST, Graph & Architecture
│
├── services/
│   ├── __init__.py
│   ├── github_service.py      # GitHub intake, validation, keyword search & metadata
│   ├── ranking_service.py     # 4-factor suitability percentage & ranking engine
│   ├── repository_service.py  # Git shallow cloning & Phase 5 static file scanner
│   ├── ast_service.py         # Phase 6 AST parsers (Python, Java, JS) & Knowledge Object
│   ├── knowledge_service.py   # Phase 7 Centralized Shared Repository Knowledge layer
│   ├── graph_service.py       # Phase 7 NetworkX Semantic Code Graph builder & validator
│   └── architecture_service.py# Phase 8 Multi-Level Architecture Explorer, Cycles & Hubs
│
├── models/
│   ├── __init__.py
│   ├── repository.py          # Dataclass model for validated repositories
│   └── knowledge.py           # Dataclass models for Shared Knowledge (Repo, File, Class, etc.)
│
├── utils/
│   ├── __init__.py
│   └── validators.py          # GitHub URL regex, segment checks, and duplicate detection
│
├── templates/
│   ├── base.html              # Base layout (header, nav, footer, toasts)
│   ├── index.html             # Academic dashboard with URL intake, queue, search & ranking
│   ├── analysis.html          # Codebase Analysis, AST Inspector & Semantic Code Graph Canvas
│   ├── architecture.html      # Phase 8 Whole Repository Architecture Explorer
│   └── graph.html             # Phase 7 Semantic Code Graph (Technical Layer)
│
├── static/
│   ├── css/
│   │   └── style.css          # Modern dashboard, inspector & canvas graph stylesheet
│   └── js/
│   │   └── main.js            # Frontend controller (intake, search, rank, clone, AST, Graph, Architecture)
│
├── data/                      # Data storage directories (git-ignored)
│   ├── repositories/          # Cloned repository workspaces (shallow clones)
│   ├── analysis/              # File scans and AST knowledge JSON caches
│   ├── graphs/                # Phase 7 generated Semantic Code Graph JSON models
│   ├── architecture/          # Phase 8 generated Whole Repository Architecture models
│   └── reports/               # Generated comprehension reports (Future Phase)
│
└── tests/
    ├── __init__.py
    ├── test_basic.py          # Application foundation and static asset tests (5 tests)
    ├── test_validation.py     # URL validation and batch queue tests (16 tests)
    ├── test_search.py         # GitHub API keyword discovery tests (12 tests)
    ├── test_ranking.py        # 4-factor suitability ranking tests (10 tests)
    ├── test_analysis.py       # Phase 5 shallow clone & file scanner tests (7 tests)
    ├── test_ast.py            # Phase 6 multi-language AST extraction tests (5 tests)
    ├── test_graph.py          # Phase 7 knowledge layer & Semantic Code Graph tests (5 tests)
    └── test_architecture.py   # Phase 8 Architecture Explorer, levels, cycles & hubs tests (15 tests)
```

---

## Installation & Setup Guide

### 1. Prerequisites
Ensure you have **Python 3.10 or higher** installed on your system:
```bash
python --version
```

### 2. Activate Virtual Environment
**On Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```
*(Or in Command Prompt: `.\.venv\Scripts\activate.bat`)*

**On macOS / Linux:**
```bash
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Optional: GitHub Token Configuration
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Optionally specify `GITHUB_TOKEN=ghp_your_token_here` in `.env` to increase GitHub API search rate limits from 60 requests/hour to 5,000 requests/hour. If omitted, all features still work completely out of the box with built-in fallbacks.

---

## How to Run the Application

With the virtual environment activated:

```powershell
python app.py
```

The application will start on:
**[http://127.0.0.1:5000](http://127.0.0.1:5000)**

Direct link to Architecture Explorer:
**[http://127.0.0.1:5000/architecture](http://127.0.0.1:5000/architecture)**

---

## Running the Automated Tests

To execute the entire automated test suite (75 tests across all 8 phases):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Expected output:
```text
Ran 75 tests in 17.311s

OK
```

---

## API Endpoints

| Method | Endpoint | Description | Payload / Query |
| :--- | :--- | :--- | :--- |
| `POST` / `GET` | `/api/repositories/search` | Search GitHub public repositories by keyword | `{"q": "Python"}` or `?q=Python` |
| `POST` | `/api/repositories/validate` | Validates a single GitHub repository URL | `{"url": "https://github.com/bottlepy/bottle"}` |
| `POST` | `/api/repositories/validate-batch` | Validates a batch of 1–10 repository URLs | `{"urls": ["..."]}` |
| `POST` | `/api/repositories/rank` | Calculates 4-factor suitability percentage & ranks candidates | `{"repositories": [...]}` |
| `POST` | `/api/repositories/acquire` | Clones repository (`--depth 1`) and performs file scan | `{"owner": "bottlepy", "name": "bottle"}` |
| `GET` | `/api/repositories/analysis/<owner>/<name>` | Retrieves cached Phase 5 static scan | N/A |
| `POST` | `/api/repositories/ast-analysis` | Performs deep AST parsing & extracts knowledge object | `{"owner": "bottlepy", "name": "bottle"}` |
| `GET` | `/api/repositories/ast-analysis/<owner>/<name>` | Retrieves cached Phase 6 AST knowledge object | N/A |
| `GET` | `/api/repositories/knowledge/<owner>/<name>` | Retrieves centralized Shared Repository Knowledge object | N/A |
| `POST` | `/api/repositories/graph` | Builds or retrieves the Semantic Code Graph | `{"owner": "bottlepy", "name": "bottle"}` |
| `GET` | `/api/repositories/graph/<owner>/<name>` | Retrieves cached Phase 7 Semantic Code Graph JSON | N/A |
| `POST` | `/api/repositories/architecture` | Builds or retrieves the Multi-Level Architecture model | `{"owner": "bottlepy", "name": "bottle"}` |
| `GET` | `/api/repositories/architecture/<owner>/<name>` | Retrieves cached Phase 8 Architecture model JSON | N/A |
| `GET` | `/api/repositories/architecture/<owner>/<name>/cycles` | Retrieves dependency cycle detection results | N/A |
| `GET` | `/health` | Application health check | N/A |

---

## Project Roadmap

| Phase | Milestone | Focus Areas | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Foundation Setup** | Modular Flask structure, templates, CSS/JS dashboard, configuration | **Complete** |
| **Phase 2** | **URL Intake & Validation** | Single & multiple GitHub URL input (1–10), validation, dynamic queue, staging | **Complete** |
| **Phase 3** | **Repository Discovery** | Keyword search via GitHub API, candidate cards, queue selection integration | **Complete** |
| **Phase 4** | **Suitability Ranking** | 4-attribute suitability evaluation (0–100%), recommendation hero, alternative ranking | **Complete** |
| **Phase 5** | **Repository Acquisition & File Scan** | Safe shallow cloning (`--depth 1`), static safety exclusions, metrics, directory tree | **Complete** |
| **Phase 6** | **Deep Static Code Analysis** | Multi-language AST parsing (Python, Java, JS), Knowledge Object, Entity Inspector UI | **Complete** |
| **Phase 7** | **Semantic Code Graph** | Shared Repository Knowledge layer, NetworkX directed graph, Canvas visualizer | **Complete** |
| **Phase 8** | **Whole Repository Architecture Explorer** | 4-tier hierarchy, dependency cycles, degree centrality hubs, architecture dossier | **Complete** |
| **Phase 9** | **Multi-Agent Comprehension & Reports** | Autonomous pattern agents, coupling risk, conversational RAG, PDF export | Planned |

---

## Academic Information

- **Project Title**: CodeLens AI: An AI-Powered Multi-Agent System for Open Source Project Analysis and Software Comprehension
- **Type**: Final-Year Academic Engineering Project
