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
      gemini_free  — google-generativeai SDK, gemini-1.5-flash model
                     Free: 15 RPM / 1M tokens per day (no billing required)
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
        self._client: Any = None
        self._initialized = False

    def _init_client(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        if self.provider == "gemini_free":
            if not self.api_key:
                print("[ai] WARNING: gemini_free selected but no api_key set in config.")
                self.provider = "none"
                return
            try:
                import google.generativeai as genai  # type: ignore[import]
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel("gemini-flash-latest")
            except ImportError:
                print("[ai] google-generativeai not installed. Run: pip install google-generativeai")
                self.provider = "none"

        elif self.provider == "groq":
            if not self.api_key:
                print("[ai] WARNING: groq selected but no api_key set in config.")
                self.provider = "none"
                return
            try:
                from groq import Groq  # type: ignore[import]
                self._client = Groq(api_key=self.api_key)
            except ImportError:
                print("[ai] groq not installed. Run: pip install groq")
                self.provider = "none"

    async def complete(self, prompt: str, max_tokens: int = 500) -> str:
        """Run the prompt through the configured provider. Returns '' if AI is disabled."""
        self._init_client()
        if self.provider == "none" or self._client is None:
            return ""

        try:
            if self.provider == "gemini_free":
                response = await asyncio.to_thread(
                    self._client.generate_content,
                    prompt,
                    generation_config={"max_output_tokens": max_tokens, "temperature": 0.4},
                )
                return response.text.strip()

            elif self.provider == "groq":
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    messages=[{"role": "user", "content": prompt}],
                    model="llama-3.1-8b-instant",
                    max_tokens=max_tokens,
                    temperature=0.4,
                )
                return response.choices[0].message.content.strip()

        except Exception as exc:
            print(f"[ai] error ({self.provider}): {exc}")
            return ""

        return ""

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
        return self.provider != "none"
