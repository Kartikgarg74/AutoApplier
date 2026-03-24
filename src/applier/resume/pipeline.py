"""Document generation pipeline - orchestrates resume + cover letter generation and PDF rendering."""

import logging
from dataclasses import dataclass

from src.ai.router import AIRouter
from src.applier.profile.loader import UserProfile
from src.applier.scoring.ai_scorer import ScoringResult

from .generator import ResumeGenerator
from .cover_letter import CoverLetterGenerator
from .pdf_builder import PDFBuilder

logger = logging.getLogger(__name__)


@dataclass
class DocumentSet:
    """Contains paths and data for a generated resume + cover letter."""
    resume_path: str = ""
    cover_letter_path: str = ""
    resume_data: dict = None
    cover_letter_text: str = ""

    def __post_init__(self):
        if self.resume_data is None:
            self.resume_data = {}


class DocumentPipeline:
    """Generates tailored resume + cover letter and renders as PDFs."""

    def __init__(self, ai_router: AIRouter, config: dict):
        self.resume_gen = ResumeGenerator(ai_router)
        self.cover_letter_gen = CoverLetterGenerator(ai_router)
        self.pdf_builder = PDFBuilder(output_dir="data/resumes")
        self.generate_cover_letter = config.get("cover_letter", {}).get("generate_for_all", True)

    async def generate_documents(self, job: dict, profile: UserProfile,
                                  scoring: ScoringResult) -> DocumentSet:
        """Generate tailored resume and cover letter, render as PDFs."""
        docs = DocumentSet()

        # 1. Generate tailored resume
        try:
            resume_data = await self.resume_gen.generate(job, profile, scoring)
            docs.resume_data = resume_data

            # Render resume PDF
            docs.resume_path = self.pdf_builder.build_resume_pdf(
                resume_data=resume_data,
                full_name=profile.personal.full_name,
                company=job.get("company", ""),
                role=job.get("title", ""),
            )
        except Exception as e:
            logger.error("Resume generation failed for %s: %s", job.get("title"), e)

        # 2. Generate cover letter
        if self.generate_cover_letter:
            try:
                cl_text = await self.cover_letter_gen.generate(job, profile, scoring)
                docs.cover_letter_text = cl_text

                # Render cover letter PDF
                docs.cover_letter_path = self.pdf_builder.build_cover_letter_pdf(
                    text=cl_text,
                    full_name=profile.personal.full_name,
                    email=profile.personal.email,
                    phone=profile.personal.phone,
                    company=job.get("company", ""),
                    role=job.get("title", ""),
                )
            except Exception as e:
                logger.error("Cover letter generation failed for %s: %s", job.get("title"), e)

        return docs
