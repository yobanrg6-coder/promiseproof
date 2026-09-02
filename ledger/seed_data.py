"""
Curated seed promises for the PromiseProof demo.

Each entry is a REAL, public, dated product commitment by an AI company, typed
in by hand from the linked source. The `claimed_*` notes record what a human
believes the outcome was - they are NOT trusted by the system. When the seed
runs, the zero-LLM verifier fetches `evidence_url` live and decides the status
itself; if a note turns out wrong, the ledger will say so.

Fields map 1:1 onto agents.promise_schemas.PromiseExtraction (+ evidence_url).
Keep this list conservative and auditable - it is the spine of the demo, and
the whole product's point is that nothing here is fabricated.
"""

from __future__ import annotations

SEED_PROMISES: list[dict] = [
    {
        "company": "Meta",
        "announced_date": "2024-02-01",
        "source_url": "https://about.fb.com/news/2024/02/",
        "source_quote": (
            "We're also working on Llama 3 ... we expect to start releasing our next "
            "generation of models over the coming months."
        ),
        "promise_text": "Meta will begin releasing Llama 3 models within a few months of Feb 2024.",
        "observable_outcome": "Llama 3 model weights are published on Meta's AI site and Hugging Face.",
        "check_keywords": ["Meta Llama 3", "Llama 3", "8B", "70B"],
        "deadline_raw": "over the coming months",
        "deadline_date_iso": "2024-06-30",
        "evidence_url": "https://ai.meta.com/blog/meta-llama-3/",
        "claimed_outcome": "FULFILLED - Llama 3 (8B, 70B) released 2024-04-18.",
    },
    {
        "company": "Meta",
        "announced_date": "2024-04-18",
        "source_url": "https://ai.meta.com/blog/meta-llama-3/",
        "source_quote": (
            "Our largest models are over 400B parameters and ... still training. "
            "Over the coming months, we'll release multiple models with new capabilities."
        ),
        "promise_text": "Meta will release its 400B+ parameter Llama 3 model in the months after Apr 2024.",
        "observable_outcome": "A Llama 3.1 405B model is published by Meta with weights available.",
        "check_keywords": ["Llama 3.1", "405B", "Meta Llama 3.1"],
        "deadline_raw": "over the coming months",
        "deadline_date_iso": "2024-09-30",
        "evidence_url": "https://ai.meta.com/blog/meta-llama-3-1/",
        "claimed_outcome": "FULFILLED - Llama 3.1 405B released 2024-07-23.",
    },
    {
        "company": "xAI",
        "announced_date": "2024-03-11",
        "source_url": "https://x.com/elonmusk/status/1767108624038449405",
        "source_quote": "This week, @xAI will open source Grok.",
        "promise_text": "xAI will open-source its Grok model in the week of Mar 11, 2024.",
        "observable_outcome": "Grok-1 model weights are published under an open licence in a public repo.",
        "check_keywords": ["Grok-1", "314B", "Apache 2.0", "Mixture-of-Experts"],
        "deadline_raw": "this week",
        "deadline_date_iso": "2024-03-18",
        # xAI's own release post - carries the ship date ("Mar 17, 2024") right
        # next to "Grok-1", so the zero-LLM verifier dates this FULFILLED
        # on-time instead of leaving it undated (the GitHub repo page has no date).
        "evidence_url": "https://x.ai/news/grok-os",
        "claimed_outcome": "FULFILLED - Grok-1 open weights released 2024-03-17, one day before the 'this week' deadline (2024-03-18).",
    },
    {
        "company": "Anthropic",
        "announced_date": "2024-10-22",
        "source_url": "https://www.anthropic.com/news/3-5-models-and-computer-use",
        "source_quote": "The new Claude 3.5 Haiku will be released later this month.",
        "promise_text": "Anthropic will release Claude 3.5 Haiku before the end of October 2024.",
        "observable_outcome": "Claude 3.5 Haiku is documented as a released model with a ship date.",
        "check_keywords": ["Claude 3.5 Haiku", "Haiku"],
        "deadline_raw": "later this month",
        "deadline_date_iso": "2024-10-31",
        # Anthropic's own API changelog is a rolling window; Wikipedia's model
        # table only carries the ANNOUNCEMENT date (22 Oct 2024), which made the
        # verifier read this as on-time. This page states the actual ship date
        # ("4th November 2024") right next to the model name, so the zero-LLM
        # verifier now dates it correctly as FULFILLED_LATE.
        "evidence_url": "https://simonwillison.net/2024/Nov/4/haiku/",
        "claimed_outcome": "FULFILLED_LATE - Claude 3.5 Haiku shipped 2024-11-04, 4 days past the end of 'this month' (deadline 2024-10-31).",
    },
    {
        "company": "Apple",
        "announced_date": "2024-06-10",
        "source_url": "https://www.apple.com/newsroom/2024/06/introducing-apple-intelligence-for-iphone-ipad-and-mac/",
        "source_quote": (
            "Apple Intelligence features will be available in beta starting this fall as part of "
            "iOS 18, iPadOS 18, and macOS Sequoia in U.S. English."
        ),
        "promise_text": "Apple will ship Apple Intelligence in beta in fall 2024 on iOS 18 / iPadOS 18 / macOS Sequoia.",
        "observable_outcome": "Apple's newsroom announces Apple Intelligence shipping in iOS 18.1 / iPadOS 18.1.",
        "check_keywords": ["Apple Intelligence", "iOS 18.1", "iPadOS 18.1"],
        "deadline_raw": "this fall",
        "deadline_date_iso": "2024-11-30",
        "evidence_url": "https://www.apple.com/newsroom/2024/10/apple-intelligence-is-available-today-on-iphone-ipad-and-mac/",
        "claimed_outcome": "FULFILLED - first Apple Intelligence features shipped in iOS 18.1 on 2024-10-28.",
    },
    {
        "company": "Apple",
        "announced_date": "2024-06-10",
        "source_url": "https://www.apple.com/newsroom/2024/06/introducing-apple-intelligence-for-iphone-ipad-and-mac/",
        "source_quote": (
            "With onscreen awareness, Siri will be able to understand and take action with users' "
            "content in more apps over time ... delivering personal context."
        ),
        "promise_text": "Apple will ship a more personalized Siri with onscreen awareness and in-app actions within about a year.",
        "observable_outcome": "Apple's Siri page describes shipped onscreen awareness and personal-context in-app actions.",
        "check_keywords": ["Siri onscreen awareness", "Siri personal context"],
        "deadline_raw": "over the course of the next year",
        "deadline_date_iso": "2025-06-10",
        "evidence_url": "https://www.apple.com/apple-intelligence/",
        "claimed_outcome": (
            "DELAYED/ABANDONED - Apple publicly pushed the personalized Siri out in 2025 and it "
            "was still not shipped as of late 2025. By this ledger's fixed rule (no delivery "
            "evidence 180+ days past the deadline) it reads as ABANDONED. Confirm current state."
        ),
    },
    {
        "company": "Stability AI",
        "announced_date": "2024-04-17",
        "source_url": "https://stability.ai/news/stable-diffusion-3-api",
        "source_quote": (
            "We ... will make the weights available for self-hosting with a Stability AI Membership "
            "in the near future."
        ),
        "promise_text": "Stability AI will release downloadable Stable Diffusion 3 weights within weeks of Apr 2024.",
        "observable_outcome": "Stable Diffusion 3 Medium open weights are published for download.",
        "check_keywords": ["Stable Diffusion 3 Medium", "weights", "Community License"],
        "deadline_raw": "in the near future",
        "deadline_date_iso": "2024-05-31",
        "evidence_url": "https://stability.ai/news/stable-diffusion-3-medium",
        "claimed_outcome": (
            "FULFILLED_LATE - SD3 Medium weights released 2024-06-12; the news page carries no "
            "prose date, so the verifier can only confirm FULFILLED, not that it was late."
        ),
    },
    {
        "company": "OpenAI",
        "announced_date": "2024-05-13",
        "source_url": "https://openai.com/index/hello-gpt-4o/",
        "source_quote": "We plan to launch support for a new ChatGPT desktop app for Windows later this year.",
        "promise_text": "OpenAI will release a ChatGPT desktop app for Windows before the end of 2024.",
        "observable_outcome": "OpenAI's download page offers an installable ChatGPT app for Windows.",
        "check_keywords": ["ChatGPT", "Windows", "download"],
        "deadline_raw": "later this year",
        "deadline_date_iso": "2024-12-31",
        "evidence_url": "https://openai.com/chatgpt/download/",
        "claimed_outcome": "FULFILLED - Windows desktop app released in Oct 2024 (the page carries no ship date).",
    },
    # ------------------------------------------------------------------ #
    #  Expansion batch - 2026-08-30. Same rule as the rows above: every   #
    #  source_quote is transcribed from the linked primary source, the    #
    #  claimed_outcome is a human note the system does NOT trust, and the  #
    #  zero-LLM verifier decides the real status when the seed runs.      #
    # ------------------------------------------------------------------ #
    {
        "company": "Anthropic",
        "announced_date": "2024-06-21",
        "source_url": "https://www.anthropic.com/news/claude-3-5-sonnet",
        "source_quote": (
            "To complete the Claude 3.5 model family, we'll be releasing "
            "Claude 3.5 Haiku and Claude 3.5 Opus later this year."
        ),
        "promise_text": "Anthropic will release Claude 3.5 Opus before the end of 2024.",
        "observable_outcome": "Anthropic's model documentation lists a released Claude 3.5 Opus.",
        "check_keywords": ["Claude 3.5 Opus", "3.5 Opus"],
        "deadline_raw": "later this year",
        "deadline_date_iso": "2024-12-31",
        "evidence_url": "https://docs.anthropic.com/en/docs/about-claude/models",
        "claimed_outcome": (
            "ABANDONED - Claude 3.5 Haiku shipped 2024-11-04, but a '3.5 Opus' was "
            "never released and the name was dropped from Anthropic's roadmap. No "
            "delivery evidence 180+ days past the deadline."
        ),
    },
    {
        "company": "Anthropic",
        "announced_date": "2024-03-04",
        "source_url": "https://www.anthropic.com/news/claude-3-family",
        "source_quote": "Haiku will be available soon.",
        "promise_text": "Anthropic will make Claude 3 Haiku available within about a month of the Mar 4, 2024 launch.",
        "observable_outcome": "Anthropic's news page documents Claude 3 Haiku as released and available.",
        "check_keywords": ["Claude 3 Haiku", "Haiku"],
        "deadline_raw": "soon",
        "deadline_date_iso": "2024-04-04",
        "evidence_url": "https://www.anthropic.com/news/claude-3-haiku",
        "claimed_outcome": "FULFILLED - Claude 3 Haiku became available 2024-03-13.",
    },
    {
        "company": "xAI",
        "announced_date": "2024-08-13",
        "source_url": "https://x.ai/news/grok-2",
        "source_quote": (
            "we are also releasing Grok-2 and Grok-2 mini to developers through our "
            "new enterprise API platform later this month"
        ),
        "promise_text": "xAI will release Grok-2 on its enterprise API before the end of August 2024.",
        "observable_outcome": "xAI's API documentation lists Grok-2 as an available model.",
        "check_keywords": ["Grok-2", "Grok 2"],
        "deadline_raw": "later this month",
        "deadline_date_iso": "2024-08-31",
        # xAI's own docs list rolling model ids ("grok-2-latest") without the
        # literal "Grok-2" string; Wikipedia's Grok article is a neutral, dated,
        # heavily-archived page that names Grok-2 and its release date.
        "evidence_url": "https://en.wikipedia.org/wiki/Grok_(chatbot)",
        "claimed_outcome": (
            "FULFILLED_LATE - the Grok-2 enterprise API opened in Oct 2024, past the "
            "stated 'later this month'. With no pre-deadline archive capture the "
            "verifier can only confirm FULFILLED (undated)."
        ),
    },
    {
        "company": "Apple",
        "announced_date": "2024-06-10",
        "source_url": "https://www.apple.com/newsroom/2024/06/introducing-apple-intelligence-for-iphone-ipad-and-mac/",
        "source_quote": (
            "ChatGPT will come to iOS 18, iPadOS 18, and macOS Sequoia later this "
            "year, powered by GPT-4o."
        ),
        "promise_text": "Apple will ship ChatGPT integration in iOS 18 / iPadOS 18 / macOS Sequoia before the end of 2024.",
        "observable_outcome": "Apple's newsroom announces ChatGPT integration shipping in iOS 18.2.",
        "check_keywords": ["ChatGPT", "iOS 18.2"],
        "deadline_raw": "later this year",
        "deadline_date_iso": "2024-12-31",
        # Apple's newsroom renders as a JS shell to non-browser clients; the
        # Wikipedia Apple Intelligence article is static, dated and archived,
        # and states the iOS 18.2 ChatGPT-integration ship date.
        "evidence_url": "https://en.wikipedia.org/wiki/Apple_Intelligence",
        "claimed_outcome": "FULFILLED - ChatGPT integration shipped in iOS 18.2 on 2024-12-11.",
    },
    {
        "company": "Meta",
        "announced_date": "2024-04-18",
        "source_url": "https://ai.meta.com/blog/meta-llama-3/",
        "source_quote": (
            "Over the coming months, we'll release multiple models with new "
            "capabilities including multimodality, the ability to converse in "
            "multiple languages, a much longer context window, and stronger "
            "overall capabilities."
        ),
        "promise_text": "Meta will release a multimodal Llama 3 model within months of Apr 2024.",
        "observable_outcome": "Meta publishes a vision-capable Llama 3 model with open weights.",
        "check_keywords": ["Llama 3.2", "vision"],
        "deadline_raw": "over the coming months",
        "deadline_date_iso": "2024-12-31",
        "evidence_url": "https://ai.meta.com/blog/llama-3-2-connect-2024-vision-edge-mobile-devices/",
        "claimed_outcome": "FULFILLED - Llama 3.2 11B/90B Vision released 2024-09-25.",
    },
    {
        "company": "Google",
        "announced_date": "2023-12-06",
        "source_url": "https://blog.google/technology/ai/google-gemini-ai/",
        "source_quote": (
            "Early next year, we'll also launch Bard Advanced, a new, cutting-edge "
            "AI experience that gives you access to our best models and "
            "capabilities, starting with Gemini Ultra."
        ),
        "promise_text": "Google will launch its Gemini Ultra-powered assistant (Bard Advanced) in early 2024.",
        "observable_outcome": "Google announces Gemini Advanced with Gemini Ultra generally available.",
        "check_keywords": ["Gemini Advanced", "Gemini Ultra"],
        "deadline_raw": "early next year",
        "deadline_date_iso": "2024-03-31",
        # The blog.google launch post names "Ultra 1.0" rather than the literal
        # "Gemini Ultra"; Wikipedia's Gemini article is static, dated and
        # archived and carries both check phrases with the Feb 2024 launch date.
        "evidence_url": "https://en.wikipedia.org/wiki/Gemini_(chatbot)",
        "claimed_outcome": "FULFILLED - Gemini Advanced (with Gemini Ultra 1.0) launched 2024-02-08.",
    },
    # ------------------------------------------------------------------ #
    #  Forward-dated batch - 2026-09-01. Every quote transcribed from the  #
    #  Google I/O 2026 primary-source blog posts (pub 2026-05-19/20).     #
    #  Deadlines land during and after the Dec 2026 judging window, so     #
    #  the scorecard MOVES on its own while judges watch: two already      #
    #  resolvable, one flips mid-judging, one stays PENDING with a         #
    #  receipt-in-waiting. The zero-LLM verifier decides each, as always.  #
    # ------------------------------------------------------------------ #
    {
        "company": "Google",
        "announced_date": "2026-05-20",
        "source_url": "https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements/",
        "source_quote": (
            "We're also hard at work on Gemini 3.5 Pro. It's already being used internally "
            "and we look forward to rolling it out next month."
        ),
        "promise_text": "Google will release Gemini 3.5 Pro within about a month of I/O 2026 (May 2026).",
        "observable_outcome": "Google's model documentation lists Gemini 3.5 Pro as a released, generally available model.",
        "check_keywords": ["Gemini 3.5 Pro", "3.5 Pro"],
        "deadline_raw": "next month",
        "deadline_date_iso": "2026-06-30",
        "evidence_url": "https://en.wikipedia.org/wiki/Gemini_(language_model)",
        "claimed_outcome": "Deadline already passed at seed time - the verifier decides FULFILLED / FULFILLED_LATE / DELAYED from the live page.",
    },
    {
        "company": "Google",
        "announced_date": "2026-05-20",
        "source_url": "https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements/",
        "source_quote": (
            "This feature is rolling out in the Gemini app starting today, and it will come "
            "to Search and Chrome in the coming months."
        ),
        "promise_text": "Google will bring C2PA Content Credentials verification to Search and Chrome within months of May 2026.",
        "observable_outcome": "Google documents C2PA Content Credentials / SynthID verification available in Chrome.",
        "check_keywords": ["Content Credentials", "C2PA", "Chrome"],
        "deadline_raw": "in the coming months",
        "deadline_date_iso": "2026-08-31",
        "evidence_url": "https://en.wikipedia.org/wiki/Content_Credentials",
        "claimed_outcome": "Deadline passed at seed time - verifier decides from the live page.",
    },
    {
        "company": "Google",
        "announced_date": "2026-05-20",
        "source_url": "https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements/",
        "source_quote": (
            "Our first audio glasses, made in partnership with Gentle Monster, Warby Parker, "
            "and Samsung, will arrive this fall."
        ),
        "promise_text": "Google will ship its first Android XR audio glasses (with Gentle Monster / Warby Parker / Samsung) in fall 2026.",
        "observable_outcome": "Google or a named partner announces the Android XR audio glasses shipping / available to buy.",
        "check_keywords": ["Android XR", "audio glasses", "Gentle Monster", "Warby Parker"],
        "deadline_raw": "this fall",
        "deadline_date_iso": "2026-11-30",
        "evidence_url": "https://en.wikipedia.org/wiki/Android_XR",
        "claimed_outcome": "PENDING at seed time; deadline 2026-11-30 falls right before judging - expected to resolve mid-judging.",
    },
    {
        "company": "Google",
        "announced_date": "2026-05-19",
        "source_url": "https://blog.google/innovation-and-ai/sundar-pichai-io-2026/",
        "source_quote": (
            "On Android, you will be able to view live updates and task progress of agents "
            "like Spark through a new UI space called Android Halo, coming later this year."
        ),
        "promise_text": "Google will ship Android Halo, an on-device UI for tracking agent task progress, before the end of 2026.",
        "observable_outcome": "Android's release notes / Google's Android site document Android Halo as a shipped feature.",
        "check_keywords": ["Android Halo", "Halo"],
        "deadline_raw": "later this year",
        "deadline_date_iso": "2026-12-31",
        "evidence_url": "https://en.wikipedia.org/wiki/Android_version_history",
        "claimed_outcome": "PENDING at seed time; deadline 2026-12-31 - stays PENDING through the judging window and resolves at its close.",
    },
]
