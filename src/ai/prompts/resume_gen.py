"""Resume generation prompt template."""

from src.utils.security import sanitize_prompt_input

RESUME_SYSTEM_PROMPT = """You are an expert resume writer specializing in ATS-optimized resumes. You tailor resumes to specific job descriptions while maintaining authenticity. Output structured JSON that can be rendered into a PDF."""


def build_resume_prompt(job_title: str, company: str, job_description: str,
                        profile_data: dict, scoring_result: dict) -> str:
    """Build the resume tailoring prompt."""
    focus_areas = scoring_result.get("resume_focus_areas", [])
    matching_skills = scoring_result.get("matching_skills", [])

    # Sanitize all external/user-controlled inputs BEFORE truncation
    safe_title = sanitize_prompt_input(job_title, 200)
    safe_company = sanitize_prompt_input(company, 200)
    safe_desc = sanitize_prompt_input(job_description, 1500)
    safe_summary = sanitize_prompt_input(str(profile_data.get('professional_summary', '')), 2000)

    return f"""Given this user profile and job description, generate a tailored resume as structured JSON.

JOB:
Title: {safe_title}
Company: {safe_company}
Description: {safe_desc}
Focus Areas: {', '.join(focus_areas)}

CANDIDATE PROFILE:
Name: {profile_data.get('personal', {}).get('full_name', '')}
Email: {profile_data.get('personal', {}).get('email', '')}
Phone: {profile_data.get('personal', {}).get('phone', '')}
LinkedIn: {profile_data.get('personal', {}).get('linkedin_url', '')}
Location: {profile_data.get('personal', {}).get('location', {}).get('city', '')}

Summary: {safe_summary}

Experience: {profile_data.get('work_experience', [])}

Education: {profile_data.get('education', [])}

Skills: {profile_data.get('skills', {{}})}

Projects: {profile_data.get('projects', [])}

Certifications: {profile_data.get('certifications', [])}

MATCHING SKILLS TO HIGHLIGHT: {', '.join(matching_skills)}

Rules:
1. Reorder skills to match job requirements (matching skills first)
2. Rewrite bullet points to incorporate job keywords naturally
3. Emphasize relevant experience, de-emphasize irrelevant
4. Keep to 1 page
5. Use ATS-friendly format (no tables, no columns, no images)
6. Use action verbs: Led, Developed, Optimized, Increased
7. Include metrics wherever possible (%, $, user count)
8. Output as structured JSON

Return JSON with this structure:
{{
    "header": {{
        "name": "...",
        "email": "...",
        "phone": "...",
        "linkedin": "...",
        "location": "..."
    }},
    "summary": "2-3 sentence tailored professional summary",
    "experience": [
        {{
            "title": "...",
            "company": "...",
            "location": "...",
            "dates": "...",
            "bullets": ["Achievement-focused bullet 1", "..."]
        }}
    ],
    "education": [
        {{
            "degree": "...",
            "institution": "...",
            "dates": "...",
            "gpa": "...",
            "highlights": ["..."]
        }}
    ],
    "skills": {{
        "technical": ["skill1", "skill2"],
        "tools": ["tool1", "tool2"],
        "soft": ["skill1"]
    }},
    "projects": [
        {{
            "name": "...",
            "description": "...",
            "technologies": "..."
        }}
    ],
    "certifications": ["cert1", "cert2"]
}}

Return ONLY valid JSON."""
