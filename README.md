# Local AI Hub

A fully secure, private, and offline AI assistant stack for local testing.

## Components
*   **Hub Dashboard:** Simple entry page at `http://localhost/` showing status of all engines.
*   **Chat Assistant (Open WebUI):** Modern user interface to chat with the model.
*   **AI Inference Core (Llama.cpp):** Pre-loaded with the **Qwen3-4B-Instruct** model.
*   **Voice Engine (Speaches):** Offline Speech-to-Text (Whisper) and Text-to-Speech (Kokoro).
*   **Memory Database (Qdrant):** Vector database for RAG (retrieval-augmented generation).

---

## How to Start

You do not need to download models or configure external services manually. The stack is fully self-contained.

Simply run:

```bash
docker compose up -d
```

Once started:
1.  Open your browser and navigate to: **[http://localhost](http://localhost)**
2.  Use the **Hub Dashboard** to check that all engines are **Online**.
3.  Click **Launch Assistant** to start chatting!
