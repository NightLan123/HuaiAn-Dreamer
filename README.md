# HuaiAn Dreamer · 槐安梦客

**A research-oriented framework for persistent AI personality, affect,
memory, and motivation.**

> What would it take for an AI system to carry more than the context of
> a single conversation---to retain experience, develop stable
> tendencies, and let its internal state shape how it responds over
> time?

HuaiAn Dreamer is an experimental, locally run software and research
project exploring that question. It connects a general-purpose language
model with a separate computational subsystem for structured
psychological and cognitive state. The project is not a new foundation
model, a character prompt library, or a claim to have created artificial
consciousness.

## Research preprint and citation

**Research preprint (Zenodo):** [DOI: 10.5281/zenodo.24593626](https://doi.org/10.5281/zenodo.24593626)

For the formal research associated with HuaiAn Dreamer, please refer to
this preprint. The paper is the scholarly reference for the research;
this repository documents the software implementation and its ongoing
development. The research preprint should not be taken as validation of
every feature in the current software or of the longer-term research
roadmap.

If you discuss or build upon the research, please cite the preprint. If
you use the software in a reproducible study, please also identify the
repository commit or release used.

## The name: HuaiAn Dreamer

The project takes its name from a short poem written for it:

> 槐安旧国曾留姓，  
> 尘世青编未载名。  
> 梦里不知身是客，  
> 醒来偏作世间人。
>
> *In Huai'an's old kingdom, my surname was once recorded;*  
> *In the world's annals, my name has yet to appear.*  
> *In dreams, I forget that I am a guest;*  
> *Awake, I still choose to be one among the people of this world.*
>
> *The English lines are a literary rendering of the original Chinese poem.*

The name joins the imagined world of Huai'an with the figure of the
*dreaming guest*. It carries a deliberately unresolved feeling: belonging
somewhere in a dream, yet waking into the human world. For this project,
that image is a reminder to approach questions of memory, identity, and
continuity with curiosity and humility—not as claims that artificial
consciousness has already been achieved.

**Public source snapshot:** `initial-source-20261127`\
**Internal protocol version:** `2.8.3-dev`\
This is the first curated public source snapshot, not a declaration that
every feature has passed end-to-end or empirical validation.

[中文说明](README.zh-CN.md) · [Project vision](docs/PROJECT_VISION.md) ·
[Architecture](docs/ARCHITECTURE.md) · [Known
limitations](docs/KNOWN_LIMITATIONS.md)

------------------------------------------------------------------------

## Why this project exists

Large language models can already produce fluent conversation and
imitate many recognizable styles. But a convincing response in one turn
does not, by itself, establish continuity across time. A system may
sound caring without retaining the experience that would make care
meaningful; it may imitate a personality without maintaining a
structured state that can constrain later decisions; it may mention a
goal without preserving it as an unfinished intention.

HuaiAn Dreamer explores a different engineering question: **can a
language model be supported by an external, persistent internal system
whose representations of personality, affect, relationships, memory, and
motivation influence later interpretation and behavior?**

The general-purpose LLM remains the language interface: it interprets
and produces natural language. The PMM subsystem is separate from that
LLM. It maintains structured state, evaluates events, retrieves and
consolidates evidence, and supplies information to deliberation and
expression. It is intended to augment a general model, not replace it or
become part of its language-generation weights.

## Conceptual architecture

``` text
People, messages, and supported events
                 │
                 ▼
       General-purpose LLM
       language understanding and expression
                 │
                 ▼
       PMM cognitive subsystem
       ├── personality and value representations
       ├── affect and slower mood dynamics
       ├── event appraisal and deliberation
       ├── relationship and boundary context
       ├── evidence-linked memory and learning
       └── expressive drive and motive tracking
                 │
                 ▼
       Structured context, proposals, and checks
                 │
                 ▼
       General-purpose LLM expresses a response
```

This is a conceptual map, not a guarantee that every pathway is fully
calibrated or behaviorally validated. The actual call sequence and
module boundaries are documented in [the architecture
guide](docs/ARCHITECTURE.md).

## What is in this source snapshot

The repository contains the Python backend, PMM-related numerical and
neural modules, the current user-facing and developer-facing interfaces,
the legacy interface, model-connection adapters, selected training
scripts, and targeted tests.

Current source capabilities include:

-   **Structured personality and identity representations.** Trait,
    value, language-style, role, and relationship information can be
    represented separately from the general language model.
-   **Affect and mood state.** The code includes event-related affect
    proposals and time-dependent affect/mood dynamics. Engineering
    parameters should not be mistaken for calibrated psychological
    constants.
-   **Event appraisal and deliberation.** PMM components organize
    evidence, context, candidate interpretations, action tendencies, and
    response-related checks.
-   **Memory lifecycle.** Interaction records can be queued for
    source-preserving consolidation. Summaries retain links to original
    evidence; memory records can be related as supporting,
    contradicting, or updating one another. Retrieval strength and decay
    are implemented as engineering models, not validated laws of human
    memory.
-   **Expressive drive and unfinished motives.** The system represents
    activation, urgency, persistence, expressive intentions, and the
    status of unfinished motives. Idle-time evaluation can assess
    whether a concrete motive meets conditions for proactive expression.
-   **Optional memory reflection.** An opt-in, scope-limited process can
    use eligible memories and owner-provided interests to propose a new
    topic or intention. It is disabled by default, bounded by request
    budgets, and requires evidence from its selected sources. A proposal
    is an internal candidate---not a factual event and not a sent
    message.
-   **User and developer interfaces.** The application provides
    conversation, character, memory, emotion, relationship,
    expressive-drive, model-configuration, and diagnostic views, with
    the exact availability depending on the current state and
    configuration.

The codebase includes API-PMM and Learned-PMM paths. The former uses a
configured model for structured interpretation; the latter provides
trainable numerical/neural representations and adapters. The public
source does **not** include private character data or a ready-made,
empirically calibrated personal model. The effect of each path depends
on configuration, training evidence, and evaluation.

## Quick start

### Requirements

-   Python **3.10 or newer**.
-   An internet connection for the first installation of runtime
    dependencies.
-   A configured language-model endpoint for real model conversations.
-   No Node.js installation or frontend build step is required for this
    snapshot.

### Windows

1.  Install Python 3.10 or newer. During installation, enable **Add
    Python to PATH**.
2.  Extract the repository to a normal writable folder.
3.  Double-click `Start_HuaiAn.cmd`.
4.  On first launch, the bootstrapper creates a project-local `.venv`
    and installs `requirements.txt` if needed. Keep the terminal window
    open to see startup output.

### macOS / Linux

``` sh
sh start_mac_linux.sh
```

### Manual launch

After installing the runtime dependencies:

``` sh
python -m pip install -r requirements.txt
python run.py
```

The application normally opens at <http://127.0.0.1:8765/>. If the
browser does not open automatically, visit that address manually. The
backend serves the current interface; opening an HTML file directly or
using a static file server will not provide the application APIs.

### First-time configuration

1.  Open **Model Settings** and configure the **General** model used for
    natural-language interaction and final responses.
2.  Configure **PMM-A** for structured psychological interpretation. It
    may use a compatible local or hosted model endpoint.
3.  Configure **PMM-B** only if you want a separate internal
    review/discussion model; it can also share the A connection where
    supported.
4.  Test each configured connection before starting a real conversation.
5.  Create or import a character in the character-management area. Begin
    with synthetic or otherwise appropriate test data before importing
    personal records.

The provider adapter includes Ollama, OpenAI-compatible Chat
Completions, OpenAI Responses, Anthropic, Gemini, and Azure chat
protocols. Actual compatibility depends on the endpoint and model. QQ
integration is disabled by default and requires separate configuration.

Optional learning dependencies, including PyTorch, can be installed
with:

``` sh
python -m pip install -r requirements-learning.txt
```

Ordinary runtime does not require PyTorch. The standalone PMM service
entry point is `run_pmm_service.py`; most users do not need to start it
separately.

## Local data and privacy

This public snapshot is designed to start with a clean, separate data
area:

-   Runtime character and conversation data default to the repository's
    `data/` directory.
-   The `.local-home/` directory stores the local data-location pointer
    and related local state.
-   Back up both directories if you want to preserve this installation's
    data.
-   Do not commit `data/`, `.local-home/`, character packages,
    diagnostic exports, logs, credentials, or API keys.

The repository does not include the original user's characters,
conversations, memories, QQ account data, model credentials, runtime
logs, private training data, or old Git history. The ignore rules are a
safeguard, not a substitute for reviewing files before committing. A
manually exported file can still be added if it is copied into the
repository and explicitly staged.

**Local storage does not mean every model request stays local.** If a
hosted provider is configured, the content sent to that provider is
subject to that provider's service and privacy terms. Review the
configured connection and its data policy before using sensitive
information.

## Development and focused checks

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the code. The
current interface is served from `ui-shell/`; the `web/` directory
provides the legacy interface. There is no frontend compilation step in
this snapshot.

Two focused checks are included:

``` sh
python -m unittest discover -s tests -p test_connection_roles_20261125.py
node tests/test_connection_roles_20261125.js
```

They cover selected connection-classification and character-management
behavior. They are not a full application test suite. The release
packaging record reports static source checks as passed, while
application/browser, hosted-model, QQ, training, and end-to-end
behavioral checks were **not run** for this packaging operation. See
[`PUBLIC_RELEASE_CHECKS.json`](PUBLIC_RELEASE_CHECKS.json) and
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

## Research roadmap

The roadmap is exploratory and does not imply a delivery date or a
validated result.

-   **Stabilize the current system:** improve the boundary-management
    path, clarify state provenance in the interface, and expand
    reproducible behavioral evaluation.
-   **Develop memory as an independent subsystem:** refine memory types,
    evidence provenance, retrieval, consolidation, contradiction
    handling, and routing between memory, affect, and motivation.
-   **Develop motivation and purpose:** investigate how unfinished
    intentions are formed, reviewed, deferred, revised, and translated
    into actions under explicit constraints.
-   **Expand environmental interaction:** evaluate multimodal inputs and
    agent/tool connections without confusing observation, inference, and
    verified events.
-   **Study learned internal representations:** evaluate Learned-PMM,
    lightweight control mechanisms, and possible cross-model transfer as
    research questions---not assumed capabilities.

## Known limitations

This is an active research codebase. In particular, the current public
snapshot documents an incomplete end-to-end interpersonal-boundary path
and incomplete boundary editing in the new interface. Initial model
parameters and candidate-learning mechanisms are not equivalent to
empirically calibrated psychological models. Hosted providers, live QQ,
real character databases, training workflows, and full multi-turn
behavior were not validated as part of this source packaging. The
complete list is maintained in
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

The project does not claim that the system is conscious, sentient, or
equivalent to a human mind. Its internal states are computational
representations whose usefulness and validity require further technical
and empirical evaluation.

## License and reuse

No project-wide open-source license has been designated in this
snapshot. Public visibility on GitHub does not, by itself, grant
permission to reuse, modify, redistribute, or commercially exploit the
source or included artwork. Please do not assume a license until the
project owner adds one. Third-party dependencies remain subject to their
own licenses.

## A note on the project

The name **HuaiAn Dreamer** carries an intentionally dreamlike image: a
visitor moving between an imagined world and ordinary life. The project
begins with a technical question, but it is motivated by a broader
curiosity about continuity---what it means to remember, to change, to
maintain boundaries, and to carry unfinished intentions from one moment
into another.

For the longer personal and research perspective, see [Project
Vision](docs/PROJECT_VISION.md).
