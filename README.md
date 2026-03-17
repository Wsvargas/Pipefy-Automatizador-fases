[readme_pipefy_automatizador.md](https://github.com/user-attachments/files/26068546/readme_pipefy_automatizador.md)
# Pipefy Phase Automation Monitor

Backend automation project that validates operational cards in **Pipefy** against **SQL Server** records and updates phase fields automatically when business rules are met.

This repository showcases my work in **process automation, API integration, SQL validation, backend development, and operational monitoring**.

---

## Business Context

In operational workflows, teams often need to manually verify whether a vehicle record in Pipefy matches the latest information stored in the internal database before moving a case forward.

This project automates that validation process by:

- reading cards from Pipefy phases,
- extracting key fields such as **chassis** and **installation date**,
- comparing them against SQL Server records,
- updating Pipefy fields when the dates match within an allowed range,
- generating traceable CSV outputs,
- exposing a monitoring panel for visibility and manual execution.

---

## What this project does

### Main goal
Automate the validation of Pipefy cards against internal SQL records to reduce manual review time, improve traceability, and support operational teams with faster processing.

### Core capabilities
- Reads cards from configured Pipefy phases via **GraphQL API**
- Retrieves **chassis** and **installation-related dates**
- Connects to **SQL Server** using `pyodbc`
- Validates whether Pipefy and SQL dates match within a configurable day range
- Updates Pipefy fields automatically when the validation passes
- Stores validated results in CSV files
- Provides a **FastAPI monitoring dashboard** with logs and downloadable outputs
- Executes automatically on startup and then every 2 hours

---

## Impact

This project is relevant to my CV because it demonstrates:

- **API integration** with Pipefy GraphQL
- **backend development** with FastAPI
- **SQL-based business validation**
- **automation of operational workflows**
- **monitoring and observability** for business processes
- **production-oriented thinking**, including logs, scheduled execution, exports, and controlled updates

---

## Architecture

![Architecture Diagram](./docs/architecture-pipefy.svg)

### Mermaid version

```mermaid
flowchart LR
    A[Pipefy Cards<br/>Z1 / Z2 phases] --> B[Core Validation Engine<br/>Python + Requests + Pandas]
    B --> C[Extract chassis and date fields]
    C --> D[SQL Server Lookup<br/>pyodbc]
    D --> E{Dates match<br/>within allowed range?}
    E -- Yes --> F[Update Pipefy fields<br/>GraphQL mutation]
    E -- No --> G[Skip update and log result]
    F --> H[CSV outputs<br/>results_z1.csv / results_z2.csv]
    G --> H
    H --> I[FastAPI Monitor]
    I --> J[Dashboard for management]
    I --> K[/logs endpoint]
    I --> L[/results endpoint]
    I --> M[/csv/z1 and /csv/z2]
```

---

## End-to-end flow

1. The monitor starts the process automatically.
2. The system reads cards from the configured Pipefy phases.
3. It extracts **chassis** and **installation date** fields.
4. It queries SQL Server for the latest valid record by chassis.
5. It compares Pipefy and SQL dates using configurable rules.
6. If the record passes validation, it updates the current Pipefy phase fields.
7. It stores successful validations in CSV output files.
8. The monitoring panel displays status, logs, and downloadable results.

---

## Technology Stack

- **Python**
- **FastAPI**
- **Pipefy GraphQL API**
- **SQL Server**
- **pyodbc**
- **pandas**
- **requests**
- **python-dotenv**
- **openpyxl**

---

## Project Structure

```bash
.
├── app.py                # FastAPI monitoring app
├── core.py               # Main validation and update pipeline
├── requirements.txt      # Project dependencies
├── data/                 # Generated CSV outputs
└── docs/
    └── architecture-pipefy.svg
```

---

## Key backend logic

### 1. Read Pipefy cards
The pipeline connects to Pipefy using GraphQL and reads cards from configured phases.

### 2. Normalize and validate dates
The system parses multiple date formats and validates whether Pipefy and SQL values fall within a configurable range.

### 3. Update current phase fields
When the business rule is satisfied, the project updates the active Pipefy phase using GraphQL mutations.

### 4. Export results
Validated cases are stored in CSV files for traceability and operational review.

### 5. Monitoring layer
A FastAPI interface exposes:
- a web dashboard,
- current execution status,
- logs,
- result tables,
- downloadable CSV files,
- a manual trigger endpoint.

---

## Environment variables

Create a `.env` file with values similar to the following:

```env
PIPEFY_TOKEN=your_pipefy_token
PIPE_ID=your_pipe_id
Z1_NAME=Z1 Agendado para instalar
Z2_NAME=Z2 Agendado para instalar

SQL_DRIVER=ODBC Driver 17 for SQL Server
SQL_SERVER=your_server
SQL_DATABASE=your_database
SQL_USER=your_user
SQL_PASSWORD=your_password

RANGO_DIAS=2
```

> Important: never commit real credentials to a public repository.

---

## API / Monitor Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Monitoring dashboard |
| `/logs` | GET | Plain text execution logs |
| `/results` | GET | Current run results in JSON |
| `/run` | POST | Triggers a manual execution |
| `/csv/z1` | GET | Downloads Z1 results |
| `/csv/z2` | GET | Downloads Z2 results |

---

## How to run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open:

```bash
http://127.0.0.1:8000
```

---

## Why this project matters

This is not just a script. It is a practical automation solution that combines:

- data validation,
- SQL integration,
- workflow automation,
- operational monitoring,
- business-rule execution,
- controlled system updates.

For recruiters and technical reviewers, this repository reflects experience in:

- backend automation,
- business process integration,
- API orchestration,
- observability,
- production-style workflow design.

---

## Recommended cleanup before using this repo as portfolio

To make this repository stronger for recruiters:

- remove `.env` from version control,
- remove generated `.json` / `.xlsx` outputs from the root,
- add a small screenshot of the monitor,
- move documentation assets into `/docs`,
- add a short section with sample business results or screenshots.

---

## Author

**Willian Steven Vargas Simbaña**  
Data Analyst | BI Analyst | Automation Developer  
GitHub: [Wsvargas](https://github.com/Wsvargas)
