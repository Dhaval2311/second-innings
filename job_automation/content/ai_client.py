"""AI client for Second Innings — routes to Gemini Free or Groq."""
from __future__ import annotations

import asyncio
import re
import warnings
from typing import TYPE_CHECKING, Any, Optional

# Suppress noisy deprecation warnings from old Python/Google SDKs
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="urllib3")

if TYPE_CHECKING:
    from ..models import Job


class AIClient:
    """
    Unified async AI client.

    Providers:
      gemini_free  — google-generativeai SDK, gemini-flash-latest model
                     Free: 15 RPM / 1,500 req per day (no billing required)
                     Key: https://aistudio.google.com/app/apikey

      groq         — groq SDK, llama-3.1-8b-instant model
                     Free tier: 14,400 req/day, 30 RPM
                     Key: https://console.groq.com

      none         — AI disabled; screening falls back to rule-based only
    """

    def __init__(self, config: dict[str, Any]) -> None:
        ai_cfg = config.get("ai", {}) or {}
        self.provider: str = ai_cfg.get("provider", "none").lower()
        self.api_key: str = ai_cfg.get("api_key", "")
        self.fallback_provider: str = ai_cfg.get("fallback_provider", "none").lower()
        self.fallback_api_key: str = ai_cfg.get("fallback_api_key", "")
        self._client: Any = None
        self._fallback_client: Any = None
        self._initialized = False
        self._primary_rate_limited = False  # set True for the session on 429

    def _build_client(self, provider: str, api_key: str) -> Any:
        """Initialise and return a client for the given provider, or None on failure."""
        if provider in ("gemini_free", "gemini"):
            if not api_key:
                print(f"[ai] WARNING: {provider} selected but no api_key set.")
                return None
            try:
                import google.generativeai as genai  # type: ignore[import]
                genai.configure(api_key=api_key)
                return genai.GenerativeModel("gemini-flash-latest")
            except ImportError:
                print("[ai] google-generativeai not installed. Run: pip install google-generativeai")
                return None

        elif provider == "openai":
            if not api_key:
                print("[ai] WARNING: openai selected but no api_key set.")
                return None
            try:
                from openai import AsyncOpenAI  # type: ignore[import]
                return AsyncOpenAI(api_key=api_key)
            except ImportError:
                print("[ai] openai not installed. Run: pip install openai")
                return None

        elif provider == "groq":
            if not api_key:
                print("[ai] WARNING: groq selected but no api_key set.")
                return None
            try:
                from groq import Groq  # type: ignore[import]
                return Groq(api_key=api_key)
            except ImportError:
                print("[ai] groq not installed. Run: pip install groq")
                return None

        return None

    def _init_client(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._client = self._build_client(self.provider, self.api_key)
        if self.fallback_provider != "none" and self.fallback_api_key:
            self._fallback_client = self._build_client(self.fallback_provider, self.fallback_api_key)

    async def _call_provider(
        self, provider: str, client: Any, prompt: str, max_tokens: int
    ) -> str:
        if provider in ("gemini_free", "gemini"):
            response = await asyncio.to_thread(
                client.generate_content,
                prompt,
                generation_config={"max_output_tokens": max_tokens, "temperature": 0.4},
            )
            return response.text.strip()

        elif provider == "openai":
            response = await client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=max_tokens,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()

        elif provider == "groq":
            response = await asyncio.to_thread(
                client.chat.completions.create,
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                max_tokens=max_tokens,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()

        return ""

    async def complete(self, prompt: str, max_tokens: int = 500) -> str:
        """Run the prompt through the configured provider, falling back to secondary on 429."""
        self._init_client()
        if self.provider == "none" or self._client is None:
            return ""

        if not self._primary_rate_limited:
            try:
                return await self._call_provider(self.provider, self._client, prompt, max_tokens)
            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "quota" in exc_str.lower() or "rate" in exc_str.lower():
                    self._primary_rate_limited = True
                    print(f"[ai] {self.provider} rate-limited — switching to {self.fallback_provider}")
                else:
                    print(f"[ai] error ({self.provider}): {exc}")
                    return ""

        # Try fallback
        if self._fallback_client is not None and self.fallback_provider != "none":
            try:
                return await self._call_provider(
                    self.fallback_provider, self._fallback_client, prompt, max_tokens
                )
            except Exception as exc:
                print(f"[ai] error ({self.fallback_provider}): {exc}")

        return ""

    async def answer_screening_questions_batch(
        self,
        questions: list[str],
        job: "Job",
        profile: dict[str, Any],
        resume_text: str = "",
    ) -> dict[str, str]:
        """
        Answer multiple form questions in a single AI call.
        Returns {question: answer}; missing entries = AI couldn't answer.
        """
        if not questions:
            return {}
        self._init_client()
        if self.provider == "none" or self._client is None:
            return {}

        profile_summary = (
            f"Name: {profile.get('full_name', '')}\n"
            f"Years experience: {profile.get('years_experience', '')}\n"
            f"Current CTC: {profile.get('current_ctc_lpa', '')} LPA\n"
            f"Expected CTC: {profile.get('expected_ctc_lpa', '')} LPA\n"
            f"Notice period: {profile.get('notice_period_days', '0')} days\n"
            f"Location: {profile.get('current_location', '')}\n"
            f"Skills: {', '.join(str(k) for k in (profile.get('skill_years') or {}).keys())}\n"
        )
        jd_snippet = job.jd_text[:600] if job.jd_text else ""
        resume_snippet = resume_text[:1200].strip() if resume_text else ""

        numbered = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        prompt = f"""You are filling in a job application form on behalf of the candidate.

Candidate profile:
{profile_summary}
{f'Resume excerpt:{chr(10)}{resume_snippet}' if resume_snippet else ''}

Job: {job.role} at {job.company}
{f'Job description excerpt: {jd_snippet}' if jd_snippet else ''}

Answer each numbered question below. Rules:
- One answer per line, format: <number>. <answer>
- Answer ONLY with the direct value (number, yes/no, short text)
- No explanations unless the question asks for a paragraph
- For years of experience with a skill, use resume/profile data
- For salary/CTC, use profile values
- If you cannot determine a confident answer, write: UNKNOWN

Questions:
{numbered}

Answers:"""

        raw = await self.complete(prompt, max_tokens=50 * len(questions))
        results: dict[str, str] = {}
        if not raw:
            return results

        for line in raw.strip().splitlines():
            m = re.match(r"^(\d+)[.)]\s*(.+)", line.strip())
            if m:
                idx = int(m.group(1)) - 1
                answer = re.sub(r"[*_`#]", "", m.group(2)).strip()
                if 0 <= idx < len(questions) and answer.upper() != "UNKNOWN":
                    results[questions[idx]] = answer
        return results

    async def answer_screening_question(
        self,
        question: str,
        job: "Job",
        profile: dict[str, Any],
        resume_text: str = "",
    ) -> Optional[str]:
        """
        Use AI to answer a screening question that rule-based logic couldn't handle.
        Returns None if AI is disabled or not confident.
        """
        self._init_client()
        if self.provider == "none" or self._client is None:
            return None

        profile_summary = (
            f"Name: {profile.get('full_name', '')}\n"
            f"Years experience: {profile.get('years_experience', '')}\n"
            f"Current CTC: {profile.get('current_ctc_lpa', '')} LPA\n"
            f"Expected CTC: {profile.get('expected_ctc_lpa', '')} LPA\n"
            f"Notice period: {profile.get('notice_period_days', '0')} days\n"
            f"Location: {profile.get('current_location', '')}\n"
            f"Skills: {', '.join(str(k) for k in (profile.get('skill_years') or {}).keys())}\n"
        )

        jd_snippet = job.jd_text[:600] if job.jd_text else ""
        resume_snippet = resume_text[:1200].strip() if resume_text else ""
        prompt = f"""You are filling in a job application form on behalf of the candidate.

Candidate profile:
{profile_summary}
{f'Resume excerpt:{chr(10)}{resume_snippet}' if resume_snippet else ''}

Job: {job.role} at {job.company}
{f'Job description excerpt: {jd_snippet}' if jd_snippet else ''}

Question from the form: "{question}"

Instructions:
- Answer ONLY with the direct answer value (number, yes/no, short text)
- Do NOT include explanations or sentences unless the question asks for a paragraph
- If asking for years of experience with a specific skill, use resume/profile data
- If asking about salary/CTC, use profile values (numbers as given in profile)
- For open-ended "why" or fit questions, write 2-3 concise sentences from the resume
- If you cannot determine a confident answer, reply with exactly: UNKNOWN

Answer:"""

        raw = await self.complete(prompt, max_tokens=100)
        if not raw or raw.strip().upper() == "UNKNOWN":
            return None
        # Strip any markdown or extra whitespace
        answer = re.sub(r"[*_`#]", "", raw).strip()
        return answer if answer else None

    async def score_job_relevance(
        self,
        job: "Job",
        resume_text: str,
    ) -> Optional[int]:
        """
        AI-based relevance score (0-100) comparing JD against resume.
        Returns None if AI is disabled or JD text is missing.
        """
        self._init_client()
        if self.provider == "none" or not job.jd_text or not resume_text:
            return None

        prompt = f"""Rate how well this resume matches the job description on a scale of 0-100.

Job: {job.role} at {job.company}
Job Description (excerpt):
{job.jd_text[:1000]}

Resume (excerpt):
{resume_text[:1000]}

Reply with ONLY a single integer from 0 to 100. No explanation.
Score:"""

        raw = await self.complete(prompt, max_tokens=10)
        match = re.search(r"\d{1,3}", raw)
        if match:
            score = int(match.group())
            return min(max(score, 0), 100)
        return None

    def is_enabled(self) -> bool:
        return self.provider not in ("none", "disabled")
