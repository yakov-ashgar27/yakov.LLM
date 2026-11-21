# yakov.LLM: Data Flow & Data Model

Drawn from the code: sync and indexing in [`yakovllm/sync.py`](../yakovllm/sync.py), [`chunker.py`](../yakovllm/chunker.py) and [`facts.py`](../yakovllm/facts.py), search in [`search.py`](../yakovllm/search.py), the HTTP API in [`server.py`](../yakovllm/server.py) and visitor memory in [`memory.py`](../yakovllm/memory.py). GitHub renders the diagrams directly.

**DFD notation:** rectangles are external entities, numbered rounded boxes are processes, cylinders are data stores.

## DFD Level 0: context diagram

```mermaid
flowchart LR
    V["Visitor<br/>(recruiter, developer)"]
    GH["GitHub<br/>Yakov's repositories"]
    LLM["LLM provider<br/>Claude · Groq · Gemini<br/>(any OpenAI-compatible)"]
    Y["Yakov (admin)"]
    SYS(("0<br/>yakov.LLM"))

    GH -- "repository contents,<br/>push webhooks" --> SYS
    V -- "questions, attached files" --> SYS
    SYS -- "answers with citations<br/>(file + lines), streamed" --> V
    SYS -- "question + top excerpts" --> LLM
    LLM -- "answer text, search keywords" --> SYS
    SYS -- "visitors, questions,<br/>unverified notes" --> Y
```

## DFD Level 1

```mermaid
flowchart TB
    V["Visitor"]
    GH["GitHub"]
    LLM["LLM provider"]
    Y["Yakov (admin)"]

    P1("1.0<br/>Sync repositories<br/>every 30 min · webhook · Action")
    P2("2.0<br/>Chunk & extract facts<br/>code · docs · pages")
    P3("3.0<br/>Search<br/>BM25 · Hebrew + code tokenizer")
    P4("4.0<br/>Answer with citations")
    P5("5.0<br/>Remember visitor")
    P6("6.0<br/>Extract attached files<br/>Word · PowerPoint · Excel · PDF")

    D1[("D1 Knowledge base<br/>kb.json: repos + ~7,200 chunks")]
    D2[("D2 BM25 index<br/>(in memory, swapped live)")]
    D3[("D3 Visitor memory<br/>memory.json, kept apart from D1")]

    GH -- "changed repos only" --> P1
    P1 -- "files with paths" --> P2
    P2 -- "chunks with line ranges,<br/>fact cards per function / file / project" --> D1
    D1 -- "rebuild" --> D2
    V -- "question" --> P3
    LLM -- "query rewrite: keywords,<br/>likely function names" --> P3
    D2 -- "ranked chunks" --> P3
    V -- "attached file" --> P6
    P6 -- "file excerpts" --> P4
    P3 -- "top excerpts" --> P4
    D3 -- "what this visitor asked before" --> P4
    P4 -- "excerpts + conversation" --> LLM
    LLM -- "answer citing [1], [2]" --> P4
    P4 -- "streamed answer (SSE),<br/>citations open exact lines" --> V
    V -- "question text" --> P5
    P5 -- "questions, names,<br/>unverified notes" --> D3
    D3 -- "memory report (admin token)" --> Y
```

## Data model

yakov.LLM has no relational database: both stores are JSON documents. The diagram shows their structure as entities, so it is clear what is kept and how the parts relate.

```mermaid
erDiagram
    REPO ||--o{ CHUNK : "split into"
    VISITOR ||--o{ QUESTION : "asked"
    VISITOR ||--o{ NOTE : "told (unverified)"

    REPO {
        string key PK "owner/name"
        string branch
        string commit "last indexed commit"
        datetime pushed_at
        string summary
        int files
        int loc
        json languages
        json facts "run commands, tests, CI, endpoints"
    }
    CHUNK {
        string id PK
        string repo FK
        string path
        int start "first line"
        int end "last line"
        string kind "code · doc · symbol · file · facts · config · page · overview"
        string title
        text text
    }
    VISITOR {
        string id PK "random id kept by the browser"
        datetime first
        datetime last
        json names
        json chats "last 50"
        json projects "question count per project"
    }
    QUESTION {
        datetime t
        string chat
        text text
        json projects
    }
    NOTE {
        datetime t
        string chat
        text text
        bool correction
        bool verified "always false until Yakov reviews"
    }
```

Visitor memory never feeds the knowledge base: what a visitor says is stored only as an unverified note. Each visitor keeps at most 40 questions and 60 notes.
