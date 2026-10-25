# Ask Ledger

A help assistant for a fictional investing app. A customer can ask questions about their own account by typed text, voice, or screenshot. The assistant answers from real account data and help-center articles, and it refuses stock picks, off-topic requests, and attempts to access other customers' accounts.

The AI runs on the company's servers. The iPhone app and the web page only send messages and display answers.

This is a learning and portfolio project, built phase by phase from a study plan.

## What it does

- **Answers account questions.** The model calls tools on a fake brokerage backend (`ledger-core`) to look up balances, withdrawals, and transfers.
- **Answers help questions with citations.** Retrieval over help-center articles (RAG), with sources cited.
- **Refuses what it should.** Stock picks, off-topic requests, jailbreaks, multi-turn attacks, and requests for other accounts.
- **Takes text, voice, and images.** Typed chat, speech-to-text and text-to-speech, and screenshot understanding with image safety checks.
- **Is measurable.** Tracing, an evaluation gate, and fallbacks.

## App screens

Mockups for the iPhone app (Phase 8). They show the behaviour the assistant is built to deliver.

| Home | Chat with a cited answer | Voice |
|------|--------------------------|-------|
| ![Home screen: greeting, pending withdrawal, suggested questions](docs/images/01-home.png) | ![Chat: IRA transfer answer with source and action buttons](docs/images/02-chat.png) | ![Voice: spoken answer about a pending withdrawal](docs/images/03-voice.png) |

| Screenshot understanding | Refusals |
|--------------------------|----------|
| ![Screenshot of a Code 214 transfer error explained in chat](docs/images/04-screenshot.png) | ![Refusals: stock pick, off-topic request, another person's account](docs/images/05-refusals.png) |

- **Home:** shows what is happening on the customer's account right now (for example a pending withdrawal), plus common questions.
- **Chat:** answers come with a source from the help center and action buttons such as "Start an IRA transfer".
- **Voice:** the customer speaks, and the answer is read aloud with its source. Tapping interrupts it.
- **Screenshot:** the customer shares an error screen. The assistant reads the error code and explains it using their account details.
- **Refusals:** the assistant declines stock picks, off-topic requests, and attempts to reset someone else's password.

## Architecture

```
iPhone app (SwiftUI) ─┐
                      ├──> Chat API ──> Model (open source) ──> ledger-core tools
Web chat page ────────┘        │                             └─> Help center search (RAG)
                               └──> Safety layer, tracing, eval gate
```

## Build plan

About 180 hours over 16 weeks (roughly 11 hours per week). Work through the phases in order.

| # | Phase | What you build |
|---|-------|----------------|
| 1 | Setup | Project folder, tools, and a big-picture video on LLMs |
| 2 | Fake brokerage | `ledger-core`: customers, logins, accounts, withdrawals, transfers (no AI) |
| 3 | Chat pipe | Chat API and a web chat page that returns a canned reply |
| 4 | Real AI model | Connect an open-source model, first on a Mac, then on a rented GPU |
| 5 | Account answers | Model calls `ledger-core` tools for account questions |
| 6 | Help center (RAG) | Help articles plus search, with cited answers |
| 7 | Safety layer | Checks for jailbreaks, off-topic requests, and multi-turn attacks |
| 8 | iPhone app | SwiftUI app built from mockups |
| 9 | Voice | Speech-to-text and text-to-speech |
| 10 | Images | Screenshot understanding and image safety |
| 11 | Monitoring | Tracing, an evaluation gate, and fallbacks |
| 12 | Package and ship | Containers, CI, runbook, portfolio |

The order is deliberate. The assistant needs account data before it can answer questions. The connection is built before the intelligence. Safety comes before more input types are added. The iPhone app comes after the backend is stable.

## Status

| Phase | Status |
|-------|--------|
| 1. Setup | In progress |
| 2–12 | Not started |

## Repository layout

Folders are added as each phase needs them. See the phase list above for what goes where.

## License

See [LICENSE](LICENSE).
