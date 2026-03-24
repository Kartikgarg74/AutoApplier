"""PDF builder - generates ATS-friendly resume and cover letter PDFs using ReportLab."""

import logging
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from src.utils.security import sanitize_for_filename, secure_directory, secure_file

logger = logging.getLogger(__name__)


def _safe_para(text: str) -> str:
    """Escape text for safe use in ReportLab Paragraph (which uses XML subset)."""
    if not text:
        return ""
    # Escape XML entities but preserve our <b> tags
    text = xml_escape(text)
    # Re-allow <b> and </b> tags
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return text


class PDFBuilder:
    """Generates ATS-friendly PDF resumes and cover letters."""

    def __init__(self, output_dir: str = "data/resumes"):
        self.output_dir = Path(output_dir)
        secure_directory(self.output_dir)

    def build_resume_pdf(self, resume_data: dict, full_name: str,
                         company: str, role: str) -> str:
        """Build an ATS-friendly resume PDF. Returns the file path."""
        safe_name = sanitize_for_filename(full_name)
        safe_company = sanitize_for_filename(company)
        safe_role = sanitize_for_filename(role)
        filename = f"{safe_name}_Resume_{safe_company}_{safe_role}.pdf"
        filepath = self.output_dir / filename

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.6 * inch,
            rightMargin=0.6 * inch,
        )

        styles = self._get_styles()
        story = []

        # Header
        header = resume_data.get("header", {})
        story.append(Paragraph(header.get("name", full_name), styles["Name"]))
        contact_parts = [
            header.get("email", ""),
            header.get("phone", ""),
            header.get("location", ""),
            header.get("linkedin", ""),
        ]
        contact_line = " | ".join(p for p in contact_parts if p)
        if contact_line:
            story.append(Paragraph(contact_line, styles["Contact"]))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5))
        story.append(Spacer(1, 6))

        # Summary
        summary = resume_data.get("summary", "")
        if summary:
            story.append(Paragraph("PROFESSIONAL SUMMARY", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            story.append(Paragraph(summary, styles["Body"]))
            story.append(Spacer(1, 8))

        # Experience
        experience = resume_data.get("experience", [])
        if experience:
            story.append(Paragraph("EXPERIENCE", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            for exp in experience:
                title_line = f"<b>{exp.get('title', '')}</b> | {exp.get('company', '')}"
                story.append(Paragraph(title_line, styles["Body"]))
                meta = f"{exp.get('location', '')} | {exp.get('dates', '')}"
                story.append(Paragraph(meta, styles["Meta"]))
                for bullet in exp.get("bullets", []):
                    story.append(Paragraph(f"- {bullet}", styles["Bullet"]))
                story.append(Spacer(1, 6))

        # Education
        education = resume_data.get("education", [])
        if education:
            story.append(Paragraph("EDUCATION", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            for edu in education:
                degree_line = f"<b>{edu.get('degree', '')}</b> | {edu.get('institution', '')}"
                story.append(Paragraph(degree_line, styles["Body"]))
                meta_parts = [edu.get("dates", "")]
                if edu.get("gpa"):
                    meta_parts.append(f"GPA: {edu['gpa']}")
                story.append(Paragraph(" | ".join(p for p in meta_parts if p), styles["Meta"]))
                for h in edu.get("highlights", []):
                    story.append(Paragraph(f"- {h}", styles["Bullet"]))
                story.append(Spacer(1, 6))

        # Skills
        skills = resume_data.get("skills", {})
        if skills:
            story.append(Paragraph("SKILLS", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            if skills.get("technical"):
                story.append(Paragraph(
                    f"<b>Technical:</b> {', '.join(skills['technical'])}",
                    styles["Body"],
                ))
            if skills.get("tools"):
                story.append(Paragraph(
                    f"<b>Tools:</b> {', '.join(skills['tools'])}",
                    styles["Body"],
                ))
            if skills.get("soft"):
                story.append(Paragraph(
                    f"<b>Soft Skills:</b> {', '.join(skills['soft'])}",
                    styles["Body"],
                ))
            story.append(Spacer(1, 6))

        # Projects
        projects = resume_data.get("projects", [])
        if projects:
            story.append(Paragraph("PROJECTS", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            for proj in projects:
                story.append(Paragraph(
                    f"<b>{proj.get('name', '')}</b> | {proj.get('technologies', '')}",
                    styles["Body"],
                ))
                story.append(Paragraph(proj.get("description", ""), styles["Bullet"]))
                story.append(Spacer(1, 4))

        # Certifications
        certs = resume_data.get("certifications", [])
        if certs:
            story.append(Paragraph("CERTIFICATIONS", styles["SectionHeader"]))
            story.append(Spacer(1, 4))
            story.append(Paragraph(", ".join(certs), styles["Body"]))

        doc.build(story)
        logger.info("Resume PDF created: %s", filepath)
        return str(filepath)

    def build_cover_letter_pdf(self, text: str, full_name: str, email: str,
                                phone: str, company: str, role: str) -> str:
        """Build a cover letter PDF. Returns the file path."""
        cl_dir = self.output_dir.parent / "cover_letters"
        secure_directory(cl_dir)

        safe_name = sanitize_for_filename(full_name)
        safe_company = sanitize_for_filename(company)
        safe_role = sanitize_for_filename(role)
        filename = f"{safe_name}_CoverLetter_{safe_company}_{safe_role}.pdf"
        filepath = cl_dir / filename

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=letter,
            topMargin=1 * inch,
            bottomMargin=1 * inch,
            leftMargin=1 * inch,
            rightMargin=1 * inch,
        )

        styles = self._get_styles()
        story = []

        # Header
        story.append(Paragraph(full_name, styles["Name"]))
        story.append(Paragraph(f"{email} | {phone}", styles["Contact"]))
        story.append(Spacer(1, 20))

        # Body paragraphs
        for paragraph in text.strip().split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                story.append(Paragraph(paragraph, styles["CLBody"]))
                story.append(Spacer(1, 12))

        doc.build(story)
        logger.info("Cover letter PDF created: %s", filepath)
        return str(filepath)

    @staticmethod
    def _get_styles():
        """Create custom styles for the PDF."""
        base = getSampleStyleSheet()

        styles = {
            "Name": ParagraphStyle(
                "Name", parent=base["Normal"],
                fontSize=16, alignment=TA_CENTER, spaceAfter=4,
                fontName="Helvetica-Bold",
            ),
            "Contact": ParagraphStyle(
                "Contact", parent=base["Normal"],
                fontSize=9, alignment=TA_CENTER, spaceAfter=2,
                fontName="Helvetica",
            ),
            "SectionHeader": ParagraphStyle(
                "SectionHeader", parent=base["Normal"],
                fontSize=11, fontName="Helvetica-Bold",
                spaceBefore=4, spaceAfter=2,
                borderWidth=0, borderPadding=0,
            ),
            "Body": ParagraphStyle(
                "Body", parent=base["Normal"],
                fontSize=10, fontName="Helvetica",
                leading=13,
            ),
            "Meta": ParagraphStyle(
                "Meta", parent=base["Normal"],
                fontSize=9, fontName="Helvetica-Oblique",
                textColor="#666666",
            ),
            "Bullet": ParagraphStyle(
                "Bullet", parent=base["Normal"],
                fontSize=10, fontName="Helvetica",
                leftIndent=12, leading=13,
            ),
            "CLBody": ParagraphStyle(
                "CLBody", parent=base["Normal"],
                fontSize=11, fontName="Helvetica",
                leading=16, alignment=TA_LEFT,
            ),
        }
        return styles
